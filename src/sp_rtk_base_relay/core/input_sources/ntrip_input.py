"""NTRIP client input source: take RTCM from an NTRIP caster (v1 or v2)."""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Any, NoReturn

from sp_rtk_base_relay.config import NtripInputConfig
from sp_rtk_base_relay.core.input_sources.base_input import (
    InputSource,
    ReconnectPolicy,
)
from sp_rtk_base_relay.core.ntrip import (
    ChunkedDecoder,
    NtripOutcome,
    get_request,
    open_connection,
    read_reply,
)
from sp_rtk_base_relay.exceptions import (
    InputSourceError,
    NtripConnectionError,
    NtripFailure,
)

logger = logging.getLogger(__name__)

_RECV_SIZE = 4096

# Replies that won't change by retrying soon: wait the policy's maximum delay.
_PERSISTENT_OUTCOMES = (
    NtripOutcome.SOURCETABLE,
    NtripOutcome.AUTH_REJECTED,
    NtripOutcome.NOT_FOUND,
)


class NtripInputSource(InputSource):
    """Reads RTCM from a caster's mountpoint as an NTRIP v1 or v2 client."""

    def __init__(self, config: NtripInputConfig) -> None:
        super().__init__("ntrip")
        self.config = config
        self._socket: socket.socket | None = None
        self._pending = b""  # body bytes that arrived with the reply
        self._decoder: ChunkedDecoder | None = None  # set when the body is chunked
        self._last_failure_persistent = False
        self._last_bytes_at = 0.0  # time.monotonic() of the last bytes from the caster
        # disconnect() may run on another thread (the hub stopping) while
        # connect() or read_data() run on the input thread. Each disconnect()
        # bumps the generation, so a connect() it interrupts doesn't install
        # its socket afterwards.
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def reconnect_policy(self) -> ReconnectPolicy:
        """The configured retry delays (default 10 s -> 120 s, x2)."""
        cfg = self.config
        return ReconnectPolicy(
            initial_delay=cfg.retry_initial_delay,
            max_delay=cfg.retry_max_delay,
            multiplier=cfg.retry_multiplier,
        )

    @property
    def last_failure_persistent(self) -> bool:
        """Whether the caster's last answer was a sourcetable, 401/403 or 404."""
        return self._last_failure_persistent

    def connect(self) -> bool:
        """Connect to the caster and request the mountpoint.

        Connected means the caster accepted the request with a reply that
        isn't a sourcetable. Bytes that arrived with the reply are kept as the
        start of the RTCM stream.

        Returns:
            True once connected; False if disconnect() was called meanwhile
            (e.g. the hub stopping).

        Raises:
            NtripConnectionError: With its reason, if the connection or the
                request failed.
        """
        self.disconnect()
        with self._lock:
            generation = self._generation
        try:
            sock, decoder, pending = self._open()
        except NtripConnectionError as error:
            self._update_connection_stats(False)
            self._last_error = error
            raise
        with self._lock:
            if generation != self._generation:
                sock.close()
                return False
            self._socket = sock
            self._decoder = decoder
            self._pending = pending
            self._last_bytes_at = time.monotonic()
            self._update_connection_stats(True)
        logger.info(
            "NTRIP input connected to %s:%d/%s (v%s)",
            self.config.caster,
            self.config.port,
            self.config.mountpoint,
            self.config.version,
        )
        return True

    def _open(self) -> tuple[socket.socket, ChunkedDecoder | None, bytes]:
        """Open the connection and request the mountpoint.

        Returns:
            The socket, the body's decoder (None unless chunked), and the RTCM
            that arrived with the reply.
        """
        cfg = self.config
        self._last_failure_persistent = False
        sock = open_connection(
            cfg.caster, cfg.port, cfg.connection_timeout, tls=cfg.tls
        )
        try:
            sock.sendall(
                get_request(
                    cfg.caster,
                    cfg.mountpoint,
                    "1.0" if cfg.version == "1.0" else "2.0",
                    cfg.username,
                    cfg.password,
                )
            )
            reply = read_reply(sock, cfg.connection_timeout)
            if reply.outcome is not NtripOutcome.ACCEPTED:
                self._last_failure_persistent = reply.outcome in _PERSISTENT_OUTCOMES
                raise self._error(
                    f"NTRIP input: caster refused the request: {reply.status_line!r}",
                    reply.failure_reason or NtripFailure.CASTER,
                )
            codings = reply.headers.get("transfer-encoding", "").lower()
            decoder = ChunkedDecoder() if "chunked" in codings else None
            try:
                pending = decoder.feed(reply.leftover) if decoder else reply.leftover
            except ValueError as e:
                raise self._error(
                    f"NTRIP input: bad chunked body from the caster: {e}",
                    NtripFailure.CASTER,
                ) from e
        except NtripConnectionError:
            sock.close()
            raise
        except OSError as e:
            sock.close()
            raise self._error(
                f"NTRIP input: caster dropped the request: {e}", NtripFailure.CASTER
            ) from e
        except BaseException:
            sock.close()
            raise
        return sock, decoder, pending

    def _error(self, message: str, reason: NtripFailure) -> NtripConnectionError:
        return NtripConnectionError(
            message,
            reason=reason,
            caster=self.config.caster,
            mountpoint=self.config.mountpoint,
        )

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read the next RTCM bytes from the caster.

        Returns None when nothing arrived in time, or when the caster closed
        the connection (the input is then disconnected and the hub
        reconnects).

        Raises:
            NtripConnectionError: ``DATA_TIMEOUT`` if no bytes have arrived for
                ``data_timeout``; ``CASTER`` if the chunked body is corrupt.
                The input is disconnected first.
        """
        if self._pending:
            data, self._pending = self._pending, b""
            self._update_read_stats(data)
            return data
        sock = self._socket
        if sock is None:
            return None

        quiet_for = time.monotonic() - self._last_bytes_at
        if quiet_for >= self.config.data_timeout:
            self._fail(
                f"NTRIP input: no data from the caster for {quiet_for:.0f}s",
                NtripFailure.DATA_TIMEOUT,
            )
        wait = self.config.data_timeout - quiet_for
        if timeout is not None:
            wait = min(wait, timeout)
        try:
            sock.settimeout(max(wait, 0.001))
            data = sock.recv(_RECV_SIZE)
        except TimeoutError:
            return None
        except OSError as e:
            self._lose_connection(InputSourceError(f"NTRIP input read error: {e}"))
            return None
        if not data:
            self._lose_connection(
                InputSourceError("NTRIP caster closed the connection")
            )
            return None
        self._last_bytes_at = time.monotonic()

        try:
            body = self._dechunk(data)
        except ValueError as e:
            self._fail(
                f"NTRIP input: bad chunked body from the caster: {e}",
                NtripFailure.CASTER,
            )
        if self._decoder is not None and self._decoder.finished:
            self._lose_connection(InputSourceError("NTRIP caster ended the stream"))
        if not body:
            return None
        self._update_read_stats(body)
        return body

    def _lose_connection(self, error: Exception) -> None:
        """The stream is gone: close the socket and record why."""
        self.disconnect()
        self._set_error_state(error)

    def _fail(self, message: str, reason: NtripFailure) -> NoReturn:
        """Drop the connection and raise a typed failure for the hub to count."""
        error = self._error(message, reason)
        self._lose_connection(error)
        raise error

    def _dechunk(self, data: bytes) -> bytes:
        """The RTCM in bytes off the socket: de-chunked if the body is chunked."""
        return self._decoder.feed(data) if self._decoder is not None else data

    def disconnect(self) -> None:
        """Close the connection to the caster (safe from any thread, and repeatable)."""
        with self._lock:
            self._generation += 1
            sock, self._socket = self._socket, None
            self._pending = b""
            self._connected = False
        if sock is not None:
            sock.close()

    def get_connection_info(self) -> dict[str, Any]:
        """Describe the caster connection, for logs and diagnostics."""
        cfg = self.config
        return {
            "type": "ntrip",
            "caster": cfg.caster,
            "port": cfg.port,
            "mountpoint": cfg.mountpoint,
            "version": cfg.version,
            "tls": cfg.tls,
            "connected": self.is_connected,
        }
