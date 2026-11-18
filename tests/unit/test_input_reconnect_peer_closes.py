"""The hub against a real TCP peer that accepts and closes each connection at
once (rtk_development#218).

Every connect() succeeds and every read finds the peer gone. Before the fix
the hub reconnected with no wait, thousands of times a second; the backoff
must hold it to a handful of attempts.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.input_sources.tcp_input import TCPConfig, TCPInputSource


@pytest.fixture
def closing_peer() -> Iterator[int]:
    """A TCP server on localhost that closes each connection as it accepts it."""
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.1)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield int(server.getsockname()[1])
    stop.set()
    thread.join(timeout=2)
    server.close()


def test_a_peer_that_closes_at_once_gets_a_handful_of_reconnects(
    closing_peer: int,
) -> None:
    hub = BroadcastHub(TCPInputSource(TCPConfig(host="127.0.0.1", port=closing_peer)))
    hub.start()
    try:
        time.sleep(1.5)
    finally:
        hub.stop()

    # One reconnect at once, then 2 s before the next.
    assert hub.stats.input_reconnect_attempts <= 2
