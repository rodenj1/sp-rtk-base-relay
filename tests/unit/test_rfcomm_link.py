"""Unit tests for the shared RFCOMM link helper.

The helper is the one place the order-sensitive Bluetooth open and
teardown live (sp-rtk-base ADR 0002). It is tested against a fake
``BluetoothManager`` and a fake socket factory, so no BlueZ or
``AF_BLUETOOTH`` support is needed.
"""

from __future__ import annotations

import errno

import pytest

from src.sp_rtk_base_relay.core.bluetooth_manager import BluetoothError
from src.sp_rtk_base_relay.core.input_sources.bluetooth_input import BluetoothConfig
from src.sp_rtk_base_relay.core.rfcomm_link import (
    RfcommConnectError,
    open_rfcomm_link,
)

MAC = "00:11:22:33:44:55"


class FakeManager:
    """A BluetoothManager stand-in that pairs only when there's no Bond."""

    def __init__(self, log: list[str], *, bonded: bool = True, channel: int = 1):
        self.log = log
        self.bonded = bonded
        self.channel = channel
        self.prepare_error: Exception | None = None
        self.disconnect_error: Exception | None = None
        self.close_error: Exception | None = None

    def ensure_device_ready(
        self,
        pin: str,
        device_name: str | None = None,
        mac_address: str | None = None,
        scan_timeout: int = 30,
    ) -> tuple[str, int]:
        if self.prepare_error is not None:
            raise self.prepare_error
        if not self.bonded:
            self.log.append(f"pair {pin}")
            self.bonded = True
        return mac_address or MAC, self.channel

    def disconnect_device(self, mac_address: str) -> bool:
        self.log.append(f"bluez_disconnect {mac_address}")
        if self.disconnect_error is not None:
            raise self.disconnect_error
        return True

    def close(self) -> None:
        self.log.append("manager_close")
        if self.close_error is not None:
            raise self.close_error


class FakeSocket:
    """An RFCOMM socket whose connect() outcome is scripted."""

    def __init__(self, log: list[str], outcome: Exception | None = None):
        self.log = log
        self.outcome = outcome
        self.timeout: float | None = None
        self.connected_to: tuple[str, int] | None = None
        self.connect_timeout: float | None = None
        self.closed = False
        self.close_error: Exception | None = None

    def settimeout(self, value: float | None) -> None:
        self.timeout = value

    def connect(self, address: tuple[str, int]) -> None:
        self.connect_timeout = self.timeout
        if self.outcome is not None:
            raise self.outcome
        self.connected_to = address

    def close(self) -> None:
        self.closed = True
        self.log.append("socket_close")
        if self.close_error is not None:
            raise self.close_error


class FakeSocketFactory:
    """Hands out sockets whose connects follow a script of outcomes."""

    def __init__(self, log: list[str], outcomes: list[Exception | None] | None = None):
        self.log = log
        self.outcomes = list(outcomes or [None])
        self.made: list[FakeSocket] = []

    def __call__(self) -> FakeSocket:
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        sock = FakeSocket(self.log, outcome)
        self.made.append(sock)
        return sock


class FakeClock:
    """A monotonic clock that only moves when the helper sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def ebusy() -> OSError:
    return OSError(errno.EBUSY, "Device or resource busy")


def open_link(
    config: BluetoothConfig,
    manager: FakeManager,
    sockets: FakeSocketFactory,
    clock: FakeClock | None = None,
    **kwargs: float,
):
    clock = clock or FakeClock()
    return open_rfcomm_link(
        manager,  # type: ignore[arg-type]
        config,
        socket_factory=sockets,  # type: ignore[arg-type]
        sleep=clock.sleep,
        monotonic=clock,
        **kwargs,
    )


class TestOpen:
    def test_connects_to_the_prepared_device_with_the_connect_timeout(self):
        log: list[str] = []
        manager = FakeManager(log, channel=3)
        sockets = FakeSocketFactory(log)
        config = BluetoothConfig(
            mac_address=MAC, connect_timeout=10.0, read_timeout=1.0
        )

        link = open_link(config, manager, sockets)

        sock = sockets.made[0]
        assert sock.connected_to == (MAC, 3)
        assert sock.connect_timeout == 10.0
        assert sock.timeout == 1.0  # reads use the read timeout
        assert link.socket is sock
        assert link.mac == MAC
        assert link.channel == 3
        assert link.manager is manager

    def test_pairs_with_the_pin_when_there_is_no_bond(self):
        log: list[str] = []
        manager = FakeManager(log, bonded=False)
        config = BluetoothConfig(mac_address=MAC, pin="1234")

        open_link(config, manager, FakeSocketFactory(log))

        assert log == ["pair 1234"]
        assert manager.bonded is True

    def test_skips_pairing_when_already_bonded(self):
        log: list[str] = []
        manager = FakeManager(log, bonded=True)

        open_link(BluetoothConfig(mac_address=MAC), manager, FakeSocketFactory(log))

        assert log == []

    def test_retries_on_ebusy_until_the_socket_connects(self):
        log: list[str] = []
        sockets = FakeSocketFactory(log, [ebusy(), ebusy(), None])
        clock = FakeClock()

        link = open_link(
            BluetoothConfig(mac_address=MAC), FakeManager(log), sockets, clock
        )

        assert len(sockets.made) == 3
        assert link.socket is sockets.made[2]
        assert sockets.made[2].connected_to == (MAC, 1)
        # Each busy socket is released before the next attempt.
        assert sockets.made[0].closed and sockets.made[1].closed
        assert not sockets.made[2].closed
        assert 0 < clock.now < 3.0

    def test_gives_up_on_ebusy_after_the_bound_with_a_clear_error(self):
        log: list[str] = []
        sockets = FakeSocketFactory(log, [ebusy()])
        clock = FakeClock()

        with pytest.raises(RfcommConnectError, match=r"busy.*2(\.0)? s") as exc_info:
            open_link(
                BluetoothConfig(mac_address=MAC),
                FakeManager(log),
                sockets,
                clock,
                busy_retry_for=2.0,
                busy_retry_interval=0.5,
            )

        assert isinstance(exc_info.value.__cause__, OSError)
        assert exc_info.value.__cause__.errno == errno.EBUSY
        assert 2.0 <= clock.now <= 2.5
        assert all(sock.closed for sock in sockets.made)

    def test_a_refused_connect_fails_at_once_and_leaves_the_manager_open(self):
        log: list[str] = []
        refused = OSError(errno.ECONNREFUSED, "Connection refused")
        sockets = FakeSocketFactory(log, [refused])
        clock = FakeClock()

        with pytest.raises(RfcommConnectError, match="Connection refused") as exc_info:
            open_link(
                BluetoothConfig(mac_address=MAC), FakeManager(log), sockets, clock
            )

        assert exc_info.value.__cause__ is refused
        assert len(sockets.made) == 1
        assert clock.now == 0.0
        # Torn down in ADR 0002's order, except the manager: the caller
        # created it and may reuse it for the next attempt.
        assert log == [f"bluez_disconnect {MAC}", "socket_close"]

    def test_a_preparation_failure_surfaces_as_a_bluetooth_error(self):
        log: list[str] = []
        manager = FakeManager(log)
        manager.prepare_error = BluetoothError("Device RTK_GPS_BASE not found")
        sockets = FakeSocketFactory(log)

        with pytest.raises(BluetoothError, match="not found"):
            open_link(BluetoothConfig(device_name="RTK_GPS_BASE"), manager, sockets)

        assert sockets.made == []
        assert log == []


class TestClose:
    def test_closes_in_adr_0002_order(self):
        log: list[str] = []
        link = open_link(
            BluetoothConfig(mac_address=MAC), FakeManager(log), FakeSocketFactory(log)
        )

        link.close()

        assert log == [f"bluez_disconnect {MAC}", "socket_close", "manager_close"]

    @pytest.mark.parametrize("failing", ["bluez_disconnect", "socket", "manager"])
    def test_attempts_every_step_when_one_fails(self, failing: str):
        log: list[str] = []
        manager = FakeManager(log)
        sockets = FakeSocketFactory(log)
        link = open_link(BluetoothConfig(mac_address=MAC), manager, sockets)
        boom = RuntimeError("boom")
        if failing == "bluez_disconnect":
            manager.disconnect_error = boom
        elif failing == "socket":
            sockets.made[0].close_error = boom
        else:
            manager.close_error = boom

        link.close()  # must not raise

        assert log == [f"bluez_disconnect {MAC}", "socket_close", "manager_close"]

    def test_attempts_every_step_when_all_fail(self):
        log: list[str] = []
        manager = FakeManager(log)
        sockets = FakeSocketFactory(log)
        link = open_link(BluetoothConfig(mac_address=MAC), manager, sockets)
        manager.disconnect_error = BluetoothError("BlueZ went away")
        sockets.made[0].close_error = OSError(errno.EBADF, "Bad file descriptor")
        manager.close_error = RuntimeError("loop already stopped")

        link.close()

        assert log == [f"bluez_disconnect {MAC}", "socket_close", "manager_close"]
