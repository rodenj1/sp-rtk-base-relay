"""Opening a TCP (optionally TLS) connection to an NTRIP caster."""

from __future__ import annotations

import socket
import ssl

from sp_rtk_base_relay.exceptions import (
    ConnectFailure,
    NtripConnectionError,
    NtripFailure,
)

# TCP keepalive settings (DR-5: passive safety net)
_TCP_KEEPALIVE_IDLE = 60  # seconds before first probe
_TCP_KEEPALIVE_INTERVAL = 10  # seconds between probes
_TCP_KEEPALIVE_COUNT = 5  # number of probes before giving up


def open_connection(
    host: str, port: int, timeout: float, *, tls: bool = False
) -> socket.socket:
    """Connect to a caster, with TCP keepalive and optional TLS.

    TLS verifies the caster's certificate and hostname against the system CA
    store; there is no way to skip verification. The returned socket keeps
    ``timeout`` as its timeout.

    Raises:
        NtripConnectionError: ``CONNECT``, with the finer cause in
            ``connect_failure``.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    in_tls_handshake = False
    try:
        sock.settimeout(timeout)
        _enable_keepalive(sock)
        sock.connect((host, port))
        if tls:
            context = ssl.create_default_context()
            sock = context.wrap_socket(
                sock, server_hostname=host, do_handshake_on_connect=False
            )
            in_tls_handshake = True
            sock.do_handshake()
        return sock
    except OSError as e:
        sock.close()
        failure = _connect_failure(e, in_tls_handshake)
        raise NtripConnectionError(
            f"NTRIP connection failed ({failure.value}): {host}:{port}: {e}",
            reason=NtripFailure.CONNECT,
            connect_failure=failure,
        ) from e


def _enable_keepalive(sock: socket.socket) -> None:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, _TCP_KEEPALIVE_IDLE)
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, _TCP_KEEPALIVE_INTERVAL
        )
    if hasattr(socket, "TCP_KEEPCNT"):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, _TCP_KEEPALIVE_COUNT)


def _connect_failure(error: OSError, in_tls_handshake: bool) -> ConnectFailure:
    if isinstance(error, ssl.SSLCertVerificationError):
        return ConnectFailure.TLS_CERTIFICATE
    if isinstance(error, TimeoutError):
        return ConnectFailure.TIMEOUT
    if isinstance(error, ssl.SSLError) or in_tls_handshake:
        return ConnectFailure.TLS_HANDSHAKE
    if isinstance(error, socket.gaierror):
        return ConnectFailure.DNS
    if isinstance(error, ConnectionRefusedError):
        return ConnectFailure.REFUSED
    return ConnectFailure.OTHER
