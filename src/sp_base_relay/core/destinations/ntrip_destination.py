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

import base64
import logging
import socket
import time
from typing import Any

from sp_base_relay import __version__
from sp_base_relay.config import (
    DestinationConfig,
    NtripDestinationConfig,
)
from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.exceptions import ConfigurationError, NtripError


logger = logging.getLogger(__name__)

# User-Agent / Source-Agent string
_USER_AGENT = f"NTRIP sp-base-relay/{__version__}"

# Timeout for the authentication handshake response (seconds)
_AUTH_RESPONSE_TIMEOUT = 10.0

# TCP keepalive settings (DR-5: passive safety net)
_TCP_KEEPALIVE_IDLE = 60  # seconds before first probe
_TCP_KEEPALIVE_INTERVAL = 10  # seconds between probes
_TCP_KEEPALIVE_COUNT = 5  # number of probes before giving up


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
    ) -> None:
        """Initialise an NTRIP destination.

        Args:
            name: Unique destination name for logging / metrics labels.
            filter_config: Message filter configuration.
            ntrip_config: NTRIP-specific config (caster, mountpoint, creds …).
            queue_size: Maximum queue depth (default 100, per DR-2).
        """
        super().__init__(name, "ntrip", filter_config, queue_size)

        self._config = ntrip_config
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

    def _connect(self) -> None:
        """Establish TCP connection and perform NTRIP auth handshake.

        Raises:
            NtripError: If connection or authentication fails.
        """
        cfg = self._config
        sock: socket.socket | None = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(float(cfg.connection_timeout))

            # Enable TCP keepalive (DR-5: passive safety net)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _TCP_KEEPALIVE_IDLE
                )
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_KEEPINTVL,
                    _TCP_KEEPALIVE_INTERVAL,
                )
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _TCP_KEEPALIVE_COUNT
                )

            logger.debug(
                f"NtripDestination '{self.name}': connecting to "
                f"{cfg.caster}:{cfg.port}"
            )
            sock.connect((cfg.caster, cfg.port))

            # Perform protocol-specific handshake
            if cfg.version == "1.0":
                self._auth_v1(sock)
            else:
                self._auth_v2(sock)

            # Switch to blocking mode with no timeout for streaming
            sock.settimeout(None)
            self._socket = sock

            logger.info(
                f"NtripDestination '{self.name}': connected to "
                f"{cfg.caster}:{cfg.port}/{cfg.mountpoint} (v{cfg.version})"
            )

        except NtripError:
            # Re-raise NTRIP-specific errors as-is
            if sock:
                sock.close()
            raise
        except OSError as e:
            if sock:
                sock.close()
            raise NtripError(
                f"NtripDestination '{self.name}': connection failed: {e}",
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
        self._next_connect_time = 0.0

    def _send_data(self, data: bytes) -> None:
        """Send RTCM data to the caster.

        For NTRIP v1.0: raw binary.
        For NTRIP v2.0: HTTP chunked transfer encoding.

        Raises:
            OSError: If the send fails (triggers reconnection).
        """
        if self._socket is None:
            raise OSError(
                f"NtripDestination '{self.name}': socket is None"
            )

        if self._config.version == "1.0":
            self._socket.sendall(data)
        else:
            # HTTP chunked encoding: <hex_length>\r\n<data>\r\n
            chunk = f"{len(data):x}\r\n".encode() + data + b"\r\n"
            self._socket.sendall(chunk)

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
        now = time.time()
        if now < self._next_connect_time:
            return

        super()._attempt_connect()

        if not self._is_connected():
            self._next_connect_time = time.time() + self._retry_delay
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
        """Reset retry delay to initial value (public, for testing)."""
        self._retry_delay = float(self._config.retry_initial_delay)
        self._next_connect_time = 0.0

    # ------------------------------------------------------------------
    # NTRIP v1.0 authentication
    # ------------------------------------------------------------------

    def _auth_v1(self, sock: socket.socket) -> None:
        """Perform NTRIP v1.0 SOURCE authentication.

        Protocol:
            SOURCE <password>\\r\\n
            Source-Agent: NTRIP sp-base-relay/x.y.z\\r\\n
            \\r\\n

        Expected response:
            ICY 200 OK\\r\\n

        Args:
            sock: Connected TCP socket.

        Raises:
            NtripError: If authentication fails.
        """
        cfg = self._config
        request = (
            f"SOURCE {cfg.password} /{cfg.mountpoint}\r\n"
            f"Source-Agent: {_USER_AGENT}\r\n"
            f"\r\n"
        )

        logger.debug(
            f"NtripDestination '{self.name}': sending v1.0 SOURCE request"
        )
        sock.sendall(request.encode("ascii"))

        response = self._read_response(sock)
        if "ICY 200 OK" not in response:
            raise NtripError(
                f"NtripDestination '{self.name}': v1.0 auth failed: {response!r}",
                destination_name=self.name,
            )

        logger.debug(
            f"NtripDestination '{self.name}': v1.0 auth successful"
        )

    # ------------------------------------------------------------------
    # NTRIP v2.0 authentication
    # ------------------------------------------------------------------

    def _auth_v2(self, sock: socket.socket) -> None:
        """Perform NTRIP v2.0 HTTP POST authentication.

        Protocol:
            POST /<mountpoint> HTTP/1.1\\r\\n
            Host: <caster>\\r\\n
            Ntrip-Version: Ntrip/2.0\\r\\n
            Authorization: Basic <base64(username:password)>\\r\\n
            User-Agent: NTRIP sp-base-relay/x.y.z\\r\\n
            Transfer-Encoding: chunked\\r\\n
            \\r\\n

        Expected response:
            HTTP/1.1 200 OK

        Args:
            sock: Connected TCP socket.

        Raises:
            NtripError: If authentication fails.
        """
        cfg = self._config
        credentials = base64.b64encode(
            f"{cfg.username}:{cfg.password}".encode("utf-8")
        ).decode("ascii")

        request = (
            f"POST /{cfg.mountpoint} HTTP/1.1\r\n"
            f"Host: {cfg.caster}\r\n"
            f"Ntrip-Version: Ntrip/2.0\r\n"
            f"Authorization: Basic {credentials}\r\n"
            f"User-Agent: {_USER_AGENT}\r\n"
            f"Transfer-Encoding: chunked\r\n"
            f"\r\n"
        )

        logger.debug(
            f"NtripDestination '{self.name}': sending v2.0 POST request"
        )
        sock.sendall(request.encode("ascii"))

        response = self._read_response(sock)
        if "200" not in response:
            raise NtripError(
                f"NtripDestination '{self.name}': v2.0 auth failed: {response!r}",
                destination_name=self.name,
            )

        logger.debug(
            f"NtripDestination '{self.name}': v2.0 auth successful"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_response(
        sock: socket.socket, timeout: float = _AUTH_RESPONSE_TIMEOUT
    ) -> str:
        """Read the authentication response from the caster.

        Reads until \\r\\n\\r\\n or timeout, whichever comes first.

        Args:
            sock: Connected TCP socket.
            timeout: Maximum time to wait for response.

        Returns:
            Response string from the caster.

        Raises:
            NtripError: If no response received within timeout.
        """
        original_timeout = sock.gettimeout()
        sock.settimeout(timeout)

        try:
            buf = b""
            while True:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buf += chunk
                if b"\r\n" in buf:
                    break
            return buf.decode("ascii", errors="replace")
        except socket.timeout as e:
            raise NtripError(
                f"NTRIP auth response timeout after {timeout}s"
            ) from e
        finally:
            sock.settimeout(original_timeout)


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
