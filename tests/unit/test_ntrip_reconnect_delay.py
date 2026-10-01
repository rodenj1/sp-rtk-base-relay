"""Tests for when a running NTRIP destination reconnects after a send error.

R2 in the NTRIP conformance audit, rodenj1/rtk_development#22.

Seam under test: a started NtripDestination fed frames with enqueue(), as
BroadcastHub feeds it, with an injected clock. The caster is a fake socket
(socket.socket patched); each socket the destination creates is one connect
attempt.
"""

import time
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from sp_rtk_base_relay.config import NtripDestinationConfig
from sp_rtk_base_relay.core.destinations.ntrip_destination import NtripDestination
from sp_rtk_base_relay.core.message_filter import FilterConfig

FRAME = bytes.fromhex("d300133ed00000000000000000000000000000000000f24bf4")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCaster:
    """Hands the destination fake sockets; can accept, drop or refuse it."""

    def __init__(self) -> None:
        self.up = True
        self.connect_attempts = 0
        self.sockets: list[MagicMock] = []

    def new_socket(self, *_args: object) -> MagicMock:
        self.connect_attempts += 1
        sock = MagicMock()
        sock.recv.return_value = b"ICY 200 OK\r\n"
        if not self.up:
            sock.connect.side_effect = ConnectionRefusedError("refused")
        self.sockets.append(sock)
        return sock

    def go_down(self) -> None:
        """Drop the live session (its next send fails) and refuse new ones."""
        self.up = False
        for sock in self.sockets:
            sock.sendall.side_effect = BrokenPipeError("Broken pipe")


@pytest.fixture
def caster() -> Iterator[FakeCaster]:
    fake = FakeCaster()
    with patch(
        "sp_rtk_base_relay.core.ntrip.connection.socket.socket",
        side_effect=fake.new_socket,
    ):
        yield fake


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def dest(caster: FakeCaster, clock: FakeClock) -> Iterator[NtripDestination]:
    config = NtripDestinationConfig(
        caster="caster.example",
        mountpoint="MP1",
        password="pw",
        version="1.0",
        retry_initial_delay=10,
        retry_max_delay=120,
        retry_multiplier=2.0,
    )
    destination = NtripDestination(
        "ntrip", FilterConfig.pass_all(), config, clock=clock
    )
    destination.start()
    yield destination
    destination.stop()


def _frames_handled(dest: NtripDestination) -> int:
    stats = dest.stats
    send_errors = stats.errors - stats.connection_failures
    return stats.messages_sent + stats.messages_dropped + send_errors


def _send_frame(dest: NtripDestination) -> None:
    """Enqueue one frame and wait until the destination has dealt with it."""
    before = _frames_handled(dest)
    dest.enqueue(FRAME)
    deadline = time.monotonic() + 5
    while _frames_handled(dest) == before:
        assert time.monotonic() < deadline, "the destination never handled the frame"
        time.sleep(0.005)


def _lose_connection(dest: NtripDestination, caster: FakeCaster) -> None:
    _send_frame(dest)  # connects and sends
    assert caster.connect_attempts == 1 and dest.is_connected
    caster.go_down()
    _send_frame(dest)  # the send fails: the session is gone
    deadline = time.monotonic() + 5
    while dest.is_connected:  # the run loop disconnects just after counting the error
        assert time.monotonic() < deadline, "the destination never disconnected"
        time.sleep(0.005)


def test_no_reconnect_within_2s_of_a_send_error(
    dest: NtripDestination, caster: FakeCaster, clock: FakeClock
) -> None:
    _lose_connection(dest, caster)

    clock.advance(1.99)
    _send_frame(dest)

    assert caster.connect_attempts == 1


def test_a_reconnect_is_attempted_at_2s(
    dest: NtripDestination, caster: FakeCaster, clock: FakeClock
) -> None:
    _lose_connection(dest, caster)
    caster.up = True  # the caster has let go of the old session

    clock.advance(2.0)
    _send_frame(dest)

    assert caster.connect_attempts == 2
    assert dest.is_connected


def test_later_failures_follow_the_configured_backoff(
    dest: NtripDestination, caster: FakeCaster, clock: FakeClock
) -> None:
    _lose_connection(dest, caster)
    clock.advance(2.0)
    _send_frame(dest)  # the 2 s retry: refused
    assert caster.connect_attempts == 2

    for attempts, delay in enumerate((10.0, 20.0, 40.0), start=3):
        clock.advance(delay - 0.1)
        _send_frame(dest)
        assert caster.connect_attempts == attempts - 1, f"retried before {delay}s"
        clock.advance(0.1)
        _send_frame(dest)
        assert caster.connect_attempts == attempts, f"not retried at {delay}s"


def test_a_restarted_destination_connects_at_once(
    dest: NtripDestination, caster: FakeCaster, clock: FakeClock
) -> None:
    # e.g. BroadcastHub.stop_destination() then start_destination()
    _lose_connection(dest, caster)
    caster.up = True
    dest.stop()
    dest.start()

    _send_frame(dest)

    assert caster.connect_attempts == 2
    assert dest.is_connected


def test_starting_a_running_destination_keeps_its_backoff(
    dest: NtripDestination, caster: FakeCaster, clock: FakeClock
) -> None:
    # e.g. BroadcastHub.start_destination() on a destination that is already running
    _lose_connection(dest, caster)
    dest.start()

    clock.advance(1.0)
    _send_frame(dest)

    assert caster.connect_attempts == 1
