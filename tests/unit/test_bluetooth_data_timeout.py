"""Tests for the Bluetooth input's data timeout (issue #75).

An RFCOMM link can stay open while the device stops sending: ``recv()`` keeps
timing out and nothing marks the input failed, so the hub never reconnects it.
``BluetoothConfig.data_timeout`` bounds that silence.

Seams under test: ``BluetoothInputSource.read_data()`` against a fake socket
and a fake clock, and a real ``BroadcastHub`` reading a real
``BluetoothInputSource`` whose BlueZ manager and RFCOMM socket are faked.
"""

import logging
import time
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from sp_rtk_base_relay.core.bluetooth_manager import BluetoothManager
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.events import INPUT_RECONNECTING, EventBus
from sp_rtk_base_relay.core.input_sources.bluetooth_input import (
    BluetoothConfig,
    BluetoothInputSource,
)
from sp_rtk_base_relay.exceptions import InputSourceError

MAC = "00:11:22:33:44:55"
CHUNK = b"\xd3\x00\x13rtcm"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SilentSocket:
    """An open RFCOMM socket: serves ``chunks``, then every recv() times out."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.closed = False

    def settimeout(self, timeout: float | None) -> None:
        pass

    def connect(self, address: tuple[str, int]) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def recv(self, size: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        time.sleep(0.001)
        raise TimeoutError("timed out")


def _manager() -> MagicMock:
    manager = MagicMock(spec=BluetoothManager)
    manager.ensure_device_ready.return_value = (MAC, 1)
    return manager


def _connected_source(
    clock: FakeClock, sock: SilentSocket, data_timeout: float = 60.0
) -> BluetoothInputSource:
    source = BluetoothInputSource(
        BluetoothConfig(mac_address=MAC, data_timeout=data_timeout),
        rfcomm_socket_factory=lambda: sock,  # type: ignore[arg-type,return-value]
        monotonic=clock,
    )
    source.bt_manager = _manager()
    assert source.connect() is True
    return source


class TestDataTimeoutConfig:
    def test_defaults_to_sixty_seconds(self) -> None:
        assert BluetoothConfig(mac_address=MAC).data_timeout == 60.0

    @pytest.mark.parametrize("value", [0, -1.0])
    def test_rejects_non_positive(self, value: float) -> None:
        with pytest.raises(InputSourceError, match="data timeout"):
            BluetoothInputSource(BluetoothConfig(mac_address=MAC, data_timeout=value))


class TestReadDataTimeout:
    def test_silence_past_data_timeout_disconnects(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock, sock = FakeClock(), SilentSocket()
        source = _connected_source(clock, sock)

        clock.now += 61.0
        with caplog.at_level(logging.WARNING):
            assert source.read_data() is None

        assert source.is_connected is False
        assert sock.closed is True
        assert "no data for 61s" in str(source.last_error)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert [r.getMessage() for r in warnings] == [
            "Bluetooth input: no data for 61s, forcing reconnect"
        ]

    def test_silence_under_data_timeout_stays_connected(self) -> None:
        clock, sock = FakeClock(), SilentSocket()
        source = _connected_source(clock, sock)

        clock.now += 59.0
        assert source.read_data() is None

        assert source.is_connected is True

    def test_bytes_reset_the_quiet_clock(self) -> None:
        clock, sock = FakeClock(), SilentSocket([CHUNK])
        source = _connected_source(clock, sock)

        clock.now += 50.0
        assert source.read_data() == CHUNK
        clock.now += 50.0
        assert source.read_data() is None

        assert source.is_connected is True

    def test_reconnected_link_gets_a_full_data_timeout(self) -> None:
        clock, sock = FakeClock(), SilentSocket()
        source = _connected_source(clock, sock)
        clock.now += 61.0
        source.read_data()
        assert source.is_connected is False

        source.bt_manager = _manager()
        assert source.connect() is True
        clock.now += 59.0
        assert source.read_data() is None

        assert source.is_connected is True


class TestHubReconnectsSilentInput:
    def test_hub_reconnects_a_silent_bluetooth_input(self) -> None:
        clock = FakeClock()
        sockets: list[SilentSocket] = []

        def socket_factory() -> SilentSocket:
            sockets.append(SilentSocket([CHUNK]))
            return sockets[-1]

        source = BluetoothInputSource(
            BluetoothConfig(mac_address=MAC, data_timeout=60.0),
            rfcomm_socket_factory=socket_factory,  # type: ignore[arg-type]
            monotonic=clock,
        )
        bus = EventBus()
        events = bus.subscribe()
        with patch(
            "sp_rtk_base_relay.core.input_sources.bluetooth_input.BluetoothManager",
            side_effect=lambda **_: _manager(),  # pyright: ignore[reportUnknownLambdaType]
        ):
            hub = BroadcastHub(
                source, [], event_bus=bus, reconnect_wait=lambda _: False
            )
            hub.start()
            try:
                clock.now += 61.0
                _wait_for(lambda: len(sockets) == 2)
                assert hub.stats.input_reconnect_attempts == 1
                assert hub.stats.input_reconnect_successes == 1
                assert sockets[0].closed is True
                assert INPUT_RECONNECTING in [e.event_type for e in events.drain()]
            finally:
                hub.stop()


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        time.sleep(0.01)
