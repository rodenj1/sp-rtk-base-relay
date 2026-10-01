"""NTRIP destination — pushes RTCM data to NTRIP casters.

Implements the NTRIP *Server* role: connects to an NTRIP Caster
(e.g. RTK2go, Onocoy, rtkdirect) and streams RTCM correction data
for distribution to rovers / NTRIP clients.

Supports both NTRIP v1.0 (SOURCE auth + raw binary) and NTRIP v2.0
(HTTP POST + Basic auth + chunked transfer encoding).

Design decisions applied:
    - DR-5: Connection health via send() failure + exponential backoff.
            TCP keepalive as passive safety net.
    - DR-6: STR records deferred — casters auto-generate from data stream.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from typing import Any

from sp_rtk_base_relay.config import (
    DestinationConfig,
    NtripDestinationConfig,
)
from sp_rtk_base_relay.core.destinations.base_destination import (
    DEFAULT_QUEUE_SIZE,
    BaseDestination,
)
from sp_rtk_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.core.ntrip import (
    NtripOutcome,
    open_connection,
    post_request,
    read_reply,
    source_request,
)
from sp_rtk_base_relay.exceptions import (
    ConfigurationError,
    NtripConnectionError,
    NtripError,
    NtripFailure,
)

logger = logging.getLogger(__name__)

# Timeout for the authentication handshake response (seconds)
_AUTH_RESPONSE_TIMEOUT = 10.0

# Wait before the first reconnect after a send error (R2 in the NTRIP conformance
# audit, rodenj1/rtk_development#22). Some casters hold the
# old session for a moment (2RTKNTRIP force-closes a same-IP reconnect within
# 1.5 s), so an immediate retry would fail; the full backoff would leave a long
# gap in corrections for one dropped connection.
_RECONNECT_DELAY_AFTER_SEND_ERROR = 2.0


class NtripDestination(BaseDestination):
    """NTRIP server destination — pushes RTCM to casters.

    Manages a direct TCP socket to the NTRIP caster, handling
    protocol handshake (v1.0 or v2.0), raw or chunked data
    streaming, and reconnection with exponential backoff.
    """

    def __init__(
        self,
        name: str,
        filter_config: FilterConfig,
        ntrip_config: NtripDestinationConfig,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialise an NTRIP destination.

        Args:
            name: Unique destination name for logging / metrics labels.
            filter_config: Message filter configuration.
            ntrip_config: NTRIP-specific config (caster, mountpoint, creds …).
            queue_size: Maximum queue depth (default 100, per DR-2).
            clock: Time source for reconnect timing, in seconds (for tests).
        """
        super().__init__(name, "ntrip", filter_config, queue_size)

        self._config = ntrip_config
        self._clock = clock
        self._socket: socket.socket | None = None

        # Backoff state
        self._retry_delay = float(ntrip_config.retry_initial_delay)
        self._next_connect_time: float = 0.0

        logger.info(
            f"NtripDestination '{name}' created → "
            f"{ntrip_config.caster}:{ntrip_config.port}/{ntrip_config.mountpoint} "
            f"(v{ntrip_config.version})"
        )

    # ------------------------------------------------------------------
    # BaseDestination abstract method implementations
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the destination; a (re)start connects at once, without backoff."""
        if not self.is_running:
            self.reset_retry_delay()
        super().start()

    def _connect(self) -> None:
        """Establish TCP connection and perform NTRIP auth handshake.

        Raises:
            NtripError: If connection or authentication fails (an
                :class:`NtripConnectionError` with a typed reason).
        """
        cfg = self._config
        logger.debug(
            f"NtripDestination '{self.name}': connecting to {cfg.caster}:{cfg.port}"
        )
        sock = open_connection(cfg.caster, cfg.port, float(cfg.connection_timeout))

        try:
            if cfg.version == "1.0":
                request = source_request(cfg.mountpoint, cfg.password)
            else:
                request = post_request(
                    cfg.caster, cfg.mountpoint, cfg.username, cfg.password
                )
            logger.debug(
                f"NtripDestination '{self.name}': sending v{cfg.version} request"
            )
            sock.sendall(request)

            reply = read_reply(sock, _AUTH_RESPONSE_TIMEOUT)
            if reply.outcome is not NtripOutcome.ACCEPTED:
                raise NtripConnectionError(
                    f"NtripDestination '{self.name}': v{cfg.version} auth failed: "
                    f"{reply.status_line!r}",
                    reason=reply.failure_reason or NtripFailure.CASTER,
                    destination_name=self.name,
                )

            # Set a generous send timeout so shutdown isn't blocked forever
            sock.settimeout(30.0)
            self._socket = sock

            logger.info(
                f"NtripDestination '{self.name}': connected to "
                f"{cfg.caster}:{cfg.port}/{cfg.mountpoint} (v{cfg.version})"
            )

        except NtripError:
            sock.close()
            raise
        except OSError as e:
            sock.close()
            raise NtripConnectionError(
                f"NtripDestination '{self.name}': connection failed: {e}",
                reason=NtripFailure.CASTER,
                destination_name=self.name,
            ) from e

    def _disconnect(self) -> None:
        """Close the TCP socket."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _send_data(self, data: bytes) -> None:
        """Send RTCM data to the caster.

        For NTRIP v1.0: raw binary.
        For NTRIP v2.0: HTTP chunked transfer encoding.

        Raises:
            OSError: If the send fails (triggers reconnection).
        """
        if self._socket is None:
            raise OSError(f"NtripDestination '{self.name}': socket is None")

        if self._config.version == "1.0":
            payload = data
        else:
            # HTTP chunked encoding: <hex_length>\r\n<data>\r\n
            payload = f"{len(data):x}\r\n".encode() + data + b"\r\n"
        try:
            self._socket.sendall(payload)
        except OSError:
            # The connection is gone; the run loop disconnects. Reconnect soon,
            # but not on the very next frame.
            self._next_connect_time = self._clock() + _RECONNECT_DELAY_AFTER_SEND_ERROR
            raise

    def _is_connected(self) -> bool:
        """Check if the TCP socket is alive."""
        return self._socket is not None

    def get_connection_info(self) -> dict[str, Any]:
        """Return connection details for logging / diagnostics."""
        return {
            "name": self.name,
            "type": "ntrip",
            "caster": self._config.caster,
            "port": self._config.port,
            "mountpoint": self._config.mountpoint,
            "version": self._config.version,
            "connected": self._socket is not None,
            "bytes_sent": self.stats.bytes_sent,
            "messages_sent": self.stats.messages_sent,
        }

    # ------------------------------------------------------------------
    # Override: backoff-aware reconnection
    # ------------------------------------------------------------------

    def _attempt_connect(self) -> None:
        """Attempt connection with exponential backoff.

        Overrides :meth:`BaseDestination._attempt_connect` to honour
        retry delay, preventing reconnection storms when the caster
        is down.
        """
        now = self._clock()
        if now < self._next_connect_time:
            return

        super()._attempt_connect()

        if not self._is_connected():
            self._next_connect_time = self._clock() + self._retry_delay
            logger.info(
                f"NtripDestination '{self.name}': next connect attempt "
                f"in {self._retry_delay:.0f}s"
            )
            self._update_retry_delay()
        else:
            # Connected — reset backoff
            self._retry_delay = float(self._config.retry_initial_delay)
            self._next_connect_time = 0.0

    def _update_retry_delay(self) -> None:
        """Increase retry delay with exponential backoff (capped)."""
        self._retry_delay = min(
            self._retry_delay * self._config.retry_multiplier,
            float(self._config.retry_max_delay),
        )

    def reset_retry_delay(self) -> None:
        """Reset retry delay to initial value and allow an immediate connect."""
        self._retry_delay = float(self._config.retry_initial_delay)
        self._next_connect_time = 0.0


# ======================================================================
# Factory builder + registration
# ======================================================================


def build_ntrip_destination(cfg: DestinationConfig) -> BaseDestination:
    """Build an :class:`NtripDestination` from a :class:`DestinationConfig`.

    This is the builder function registered with
    :class:`DestinationFactory` for the ``"ntrip"`` type.

    Args:
        cfg: Parsed destination config entry.

    Returns:
        Configured :class:`NtripDestination` instance.

    Raises:
        ConfigurationError: If ``cfg.config`` is not an
            :class:`NtripDestinationConfig`.
    """
    if not isinstance(cfg.config, NtripDestinationConfig):
        raise ConfigurationError(
            f"Expected NtripDestinationConfig for destination '{cfg.name}', "
            f"got {type(cfg.config).__name__}",
            config_key=f"destinations[{cfg.name}].config",
        )

    filter_config = cfg.filter.to_filter_config()
    return NtripDestination(
        name=cfg.name,
        filter_config=filter_config,
        ntrip_config=cfg.config,
    )


# Auto-register when module is imported
DestinationFactory.register("ntrip", build_ntrip_destination)
