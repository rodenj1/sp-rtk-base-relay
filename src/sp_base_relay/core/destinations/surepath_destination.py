"""Sure-Path destination — wraps RTCMClient behind BaseDestination.

Thin adapter that composes the production-proven RTCMClient (INIT auth,
$HB$ heartbeat, exponential backoff) with the v2 BaseDestination
interface (queue, filter, stats, thread lifecycle).

Design:
    - Composition over inheritance: SurePathDestination *has-a* RTCMClient
    - RTCMClient manages its own socket/auth/heartbeat lifecycle
    - BaseDestination._run_loop detects disconnection via _is_connected()
    - Exponential backoff is delegated to RTCMClient's retry logic
    - _attempt_connect() is overridden to honour the backoff delay
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sp_base_relay.config import (
    DestinationConfig,
    SurePathDestinationConfig,
)
from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.core.rtcm_client import RTCMClient
from sp_base_relay.exceptions import ConfigurationError, DestinationError


logger = logging.getLogger(__name__)


class SurePathDestination(BaseDestination):
    """Sure-Path RTCM server destination.

    Wraps :class:`RTCMClient` behind the :class:`BaseDestination` interface
    so it can be managed by :class:`BroadcastHub` alongside other
    destination types.

    The underlying ``RTCMClient`` handles:

    * TCP connection to the Sure-Path server
    * ``INIT:user:pass*`` authentication handshake
    * ``$HB$`` heartbeat monitoring in a background thread
    * Exponential back-off on connection failures

    This class adds:

    * Per-destination queue + filter (from ``BaseDestination``)
    * Back-off aware reconnection (overrides ``_attempt_connect``)
    * Aggregated stats merging RTCMClient stats into DestinationStats
    """

    def __init__(
        self,
        name: str,
        filter_config: FilterConfig,
        surepath_config: SurePathDestinationConfig,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        """Initialise a Sure-Path destination.

        Args:
            name: Unique destination name for logging / metrics labels.
            filter_config: Message filter configuration.
            surepath_config: Sure-Path–specific config (host, port, creds …).
            queue_size: Maximum queue depth (default 100, per DR-2).
        """
        super().__init__(name, "surepath", filter_config, queue_size)

        # Convert v2 config → v1 RTCMServerConfig expected by RTCMClient
        self._rtcm_server_config = surepath_config.to_rtcm_server_config()
        self._client = RTCMClient(self._rtcm_server_config)

        # Back-off tracking — prevents hammering the server every time
        # a queued frame arrives while we're in a retry window.
        self._next_connect_time: float = 0.0

        logger.info(
            f"SurePathDestination '{name}' created → "
            f"{self._rtcm_server_config.host}:{self._rtcm_server_config.port}"
        )

    # ------------------------------------------------------------------
    # BaseDestination abstract method implementations
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Establish connection via RTCMClient (auth + heartbeat)."""
        success = self._client.connect()
        if not success:
            raise DestinationError(
                f"SurePathDestination '{self.name}': RTCMClient.connect() failed",
                destination_name=self.name,
            )

    def _disconnect(self) -> None:
        """Disconnect the underlying RTCMClient."""
        self._client.disconnect()
        # Reset back-off so next connect attempt happens immediately
        self._next_connect_time = 0.0

    def _send_data(self, data: bytes) -> None:
        """Send RTCM data through RTCMClient.

        Raises:
            OSError: If the send fails (triggers reconnection in run_loop).
        """
        if not self._client.send_rtcm_data(data):
            raise OSError(
                f"SurePathDestination '{self.name}': send_rtcm_data returned False"
            )

    def _is_connected(self) -> bool:
        """Check RTCMClient connection state."""
        return self._client.is_connected

    def get_connection_info(self) -> dict[str, Any]:
        """Return connection details for logging / diagnostics."""
        client_stats = self._client.connection_statistics
        return {
            "name": self.name,
            "type": "surepath",
            "host": self._rtcm_server_config.host,
            "port": self._rtcm_server_config.port,
            "connected": self._client.is_connected,
            "state": self._client.connection_state.value,
            "bytes_sent": client_stats.bytes_sent,
            "messages_sent": client_stats.messages_sent,
            "heartbeat_timeouts": client_stats.heartbeat_timeouts,
            "auth_failures": client_stats.authentication_failures,
        }

    # ------------------------------------------------------------------
    # Override: back-off–aware reconnection
    # ------------------------------------------------------------------

    def _attempt_connect(self) -> None:
        """Attempt connection with exponential back-off.

        Overrides :meth:`BaseDestination._attempt_connect` to honour
        ``RTCMClient``'s retry delay, preventing reconnection storms
        when the server is down.
        """
        now = time.time()
        if now < self._next_connect_time:
            # Still in back-off window — skip this attempt
            return

        # Delegate to base class (tracks stats, clears queue on success)
        super()._attempt_connect()

        if not self._is_connected():
            # Connection failed — schedule next attempt using RTCMClient
            # backoff delay.
            retry_delay = self._client.get_retry_delay()
            self._next_connect_time = time.time() + retry_delay
            logger.info(
                f"SurePathDestination '{self.name}': next connect attempt "
                f"in {retry_delay}s"
            )
        else:
            # Connected — reset backoff in RTCMClient for future failures
            self._next_connect_time = 0.0

    # ------------------------------------------------------------------
    # Merged stats helper
    # ------------------------------------------------------------------

    @property
    def client_stats(self) -> Any:
        """Expose underlying RTCMClient connection stats (read-only).

        Useful for metrics that need RTCMClient-level detail like
        heartbeat_timeouts and authentication_failures.
        """
        return self._client.connection_statistics


# ======================================================================
# Factory builder + registration
# ======================================================================


def build_surepath_destination(cfg: DestinationConfig) -> BaseDestination:
    """Build a :class:`SurePathDestination` from a :class:`DestinationConfig`.

    This is the builder function registered with
    :class:`DestinationFactory` for the ``"surepath"`` type.

    Args:
        cfg: Parsed destination config entry.

    Returns:
        Configured :class:`SurePathDestination` instance.

    Raises:
        ConfigurationError: If ``cfg.config`` is not a
            :class:`SurePathDestinationConfig`.
    """
    if not isinstance(cfg.config, SurePathDestinationConfig):
        raise ConfigurationError(
            f"Expected SurePathDestinationConfig for destination '{cfg.name}', "
            f"got {type(cfg.config).__name__}",
            config_key=f"destinations[{cfg.name}].config",
        )

    filter_config = cfg.filter.to_filter_config()
    return SurePathDestination(
        name=cfg.name,
        filter_config=filter_config,
        surepath_config=cfg.config,
    )


# Auto-register when module is imported
DestinationFactory.register("surepath", build_surepath_destination)
