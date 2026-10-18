"""Unit tests for the Bluetooth link strength reading in Input status.

A connected Bluetooth input reports the adapter's HCI ``Read RSSI`` for its
link as ``InputStatus.link_rssi``. The tests drive the Bluetooth input
source's status through ``build_input_status``, with a fake RFCOMM socket,
a fake raw HCI socket factory and a fake clock, so no BlueZ or
``AF_BLUETOOTH`` support is needed.
"""

from __future__ import annotations

import errno
import struct

import pytest

from src.sp_rtk_base_relay.core.hci_link_info import bind_hci
from src.sp_rtk_base_relay.core.input_sources.bluetooth_input import (
    BluetoothConfig,
    BluetoothInputSource,
)
from src.sp_rtk_base_relay.core.input_sources.tcp_input import (
    TCPConfig,
    TCPInputSource,
)
from src.sp_rtk_base_relay.core.status import InputStatus, build_input_status

MAC = "00:11:22:33:44:55"
ACL_HANDLE = 0x0042
OP_READ_RSSI = 0x1405


class FakeClock:
    """A monotonic clock that moves only when a fake socket waits."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeManager:
    """A BluetoothManager stand-in for a device that is already bonded."""

    def ensure_device_ready(self, **_: object) -> tuple[str, int]:
        return MAC, 1

    def disconnect_device(self, mac_address: str) -> bool:
        return True

    def close(self) -> None:
        pass


class FakeRfcommSocket:
    """A connected RFCOMM socket that reports its ACL connection handle."""

    def __init__(self, handle: int = ACL_HANDLE) -> None:
        self.handle = handle
        self.conninfo_error: OSError | None = None

    def settimeout(self, value: float | None) -> None:
        pass

    def connect(self, address: tuple[str, int]) -> None:
        pass

    def getsockopt(self, level: int, option: int, buflen: int = 0) -> bytes:
        assert (level, option) == (18, 2)  # SOL_RFCOMM, RFCOMM_CONNINFO
        if self.conninfo_error is not None:
            raise self.conninfo_error
        return struct.pack("<H3s", self.handle, b"\x00\x1f\x00")

    def recv(self, bufsize: int) -> bytes:
        raise TimeoutError

    def close(self) -> None:
        pass


def command_complete(rssi: int, *, status: int = 0, handle: int = ACL_HANDLE) -> bytes:
    """An HCI Command Complete event answering Read RSSI."""
    params = struct.pack("<BHBHb", 1, OP_READ_RSSI, status, handle, rssi)
    return struct.pack("<BBB", 0x04, 0x0E, len(params)) + params


class FakeHciSocket:
    """A raw HCI socket that answers with a script of replies.

    Each reply is the bytes one ``recv`` returns, or an exception it
    raises. Once the script is used up, ``recv`` waits out its timeout on
    the fake clock and times out, as a silent adapter would.
    """

    def __init__(self, clock: FakeClock, replies: list[bytes | Exception]) -> None:
        self.clock = clock
        self.replies = list(replies)
        self.timeout: float | None = None
        self.sent: list[bytes] = []
        self.closed = False
        self.wait_per_reply = 0.0

    def setsockopt(self, level: int, option: int, value: bytes) -> None:
        pass

    def settimeout(self, value: float | None) -> None:
        if value is not None and value < 0:
            raise ValueError("Timeout value out of range")
        self.timeout = value

    def send(self, data: bytes) -> int:
        self.sent.append(data)
        return len(data)

    def recv(self, bufsize: int) -> bytes:
        limit = self.timeout if self.timeout is not None else 3600.0
        if not self.replies or self.wait_per_reply > limit:
            self.clock.now += limit
            raise TimeoutError("timed out")
        reply = self.replies.pop(0)
        self.clock.now += self.wait_per_reply
        if isinstance(reply, Exception):
            raise reply
        return reply

    def close(self) -> None:
        self.closed = True


class FakeHciSocketFactory:
    """Hands out one scripted HCI socket per call, bound to an adapter index."""

    def __init__(
        self, clock: FakeClock, replies: list[bytes | Exception] | None = None
    ) -> None:
        self.clock = clock
        self.replies = replies or []
        self.error: OSError | None = None
        self.wait_per_reply = 0.0
        self.adapters: list[int] = []
        self.made: list[FakeHciSocket] = []

    def __call__(self, adapter_index: int) -> FakeHciSocket:
        self.adapters.append(adapter_index)
        if self.error is not None:
            raise self.error
        sock = FakeHciSocket(self.clock, self.replies)
        sock.replies = self.replies  # one script, shared across readings
        sock.wait_per_reply = self.wait_per_reply
        self.made.append(sock)
        return sock


def connected_source(
    hci: FakeHciSocketFactory,
    clock: FakeClock,
    rfcomm: FakeRfcommSocket | None = None,
    adapter_name: str = "hci0",
) -> BluetoothInputSource:
    source = BluetoothInputSource(
        BluetoothConfig(mac_address=MAC, adapter_name=adapter_name),
        rfcomm_socket_factory=lambda: rfcomm or FakeRfcommSocket(),  # type: ignore[arg-type,return-value]
        hci_socket_factory=hci,  # type: ignore[arg-type]
        monotonic=clock,
    )
    source.bt_manager = FakeManager()  # type: ignore[assignment]
    source.connect()
    return source


class TestConnectedLink:
    @pytest.mark.parametrize("rssi", [0, -7, 3])
    def test_reports_the_reading_the_adapter_returns(self, rssi: int):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(rssi)])

        status = build_input_status(connected_source(hci, clock))

        assert status.link_rssi == rssi

    def test_asks_about_the_links_own_connection_handle(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(-2, handle=0x0B)])

        status = build_input_status(
            connected_source(hci, clock, FakeRfcommSocket(handle=0x0B))
        )

        assert status.link_rssi == -2
        # 01 | opcode 0x1405 | plen 2 | handle 0x000B
        assert hci.made[0].sent == [bytes.fromhex("010514020b00")]

    def test_ignores_a_reply_about_another_connection(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(
            clock, [command_complete(-20, handle=0x0099), command_complete(-4)]
        )

        status = build_input_status(connected_source(hci, clock))

        assert status.link_rssi == -4

    def test_reads_the_adapter_named_in_the_config(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(0)])

        build_input_status(connected_source(hci, clock, adapter_name="hci1"))

        assert hci.adapters == [1]

    def test_closes_the_hci_socket_after_each_reading(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(0)])

        build_input_status(connected_source(hci, clock))

        assert [sock.closed for sock in hci.made] == [True]

    def test_takes_a_fresh_reading_each_time_the_status_is_built(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(0), command_complete(-6)])
        source = connected_source(hci, clock)
        assert hci.made == []  # nothing is read until a status is built

        first = build_input_status(source)
        second = build_input_status(source)

        assert (first.link_rssi, second.link_rssi) == (0, -6)
        assert len(hci.made) == 2


class TestNoReading:
    def test_unavailable_127_is_no_reading(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(127)])

        assert build_input_status(connected_source(hci, clock)).link_rssi is None

    def test_an_hci_error_status_is_no_reading(self):
        clock = FakeClock()
        # 0x02: Unknown Connection Identifier
        hci = FakeHciSocketFactory(clock, [command_complete(0, status=0x02)])

        assert build_input_status(connected_source(hci, clock)).link_rssi is None

    def test_a_command_status_error_is_no_reading(self):
        clock = FakeClock()
        command_status = struct.pack("<BBBBBH", 0x04, 0x0F, 4, 0x0C, 1, OP_READ_RSSI)
        hci = FakeHciSocketFactory(clock, [command_status])

        assert build_input_status(connected_source(hci, clock)).link_rssi is None
        assert clock.now == 0.0  # settled at once, not by the timeout

    def test_no_reply_gives_up_within_the_timeout(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [])
        source = connected_source(hci, clock)

        status = build_input_status(source)

        assert status.link_rssi is None
        assert 0 < clock.now <= 0.5

    def test_a_stream_of_unrelated_events_gives_up_within_the_timeout(self):
        clock = FakeClock()
        other = struct.pack("<BBBBHB", 0x04, 0x0E, 4, 1, 0x0C14, 0)
        hci = FakeHciSocketFactory(clock, [other] * 100)
        hci.wait_per_reply = 0.2
        source = connected_source(hci, clock)

        status = build_input_status(source)

        assert status.link_rssi is None
        assert 0.4 <= clock.now <= 0.5

    def test_a_link_torn_down_mid_read_is_no_reading(self):
        clock = FakeClock()
        rfcomm = FakeRfcommSocket()
        rfcomm.conninfo_error = OSError(errno.ENOTCONN, "Transport not connected")
        hci = FakeHciSocketFactory(clock, [command_complete(0)])

        status = build_input_status(connected_source(hci, clock, rfcomm))

        assert status.link_rssi is None
        assert hci.made == []

    @pytest.mark.parametrize(
        "error",
        [
            OSError(errno.EPERM, "Operation not permitted"),
            OSError(errno.ENODEV, "No such device"),
        ],
    )
    def test_an_hci_socket_that_wont_open_is_no_reading(self, error: OSError):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock)
        hci.error = error

        assert build_input_status(connected_source(hci, clock)).link_rssi is None

    def test_a_failing_hci_read_is_no_reading_and_closes_the_socket(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [OSError(errno.ENETDOWN, "Network down")])

        status = build_input_status(connected_source(hci, clock))

        assert status.link_rssi is None
        assert hci.made[0].closed

    def test_a_disconnected_link_is_no_reading(self):
        clock = FakeClock()
        hci = FakeHciSocketFactory(clock, [command_complete(0)])
        source = connected_source(hci, clock)
        source.disconnect()

        status = build_input_status(source)

        assert status.link_rssi is None
        assert hci.made == []

    def test_a_non_bluetooth_input_has_no_reading(self):
        source = TCPInputSource(TCPConfig(host="127.0.0.1", port=2101))

        assert build_input_status(source).link_rssi is None


class TestInputStatusCompatibility:
    def test_input_status_built_without_the_field_has_no_reading(self):
        status = InputStatus(
            connected=True,
            source_type="tcp",
            bytes_received=0,
            messages_received=0,
            seconds_since_last_data=-1.0,
            reconnect_attempts=0,
            reconnect_successes=0,
            connected_since=None,
        )

        assert status.link_rssi is None


class TestBindHci:
    """The raw HCI bind works around cpython#132075 where it is unfixed."""

    class _Sock:
        def __init__(self) -> None:
            self.bound: object = None

        def fileno(self) -> int:
            return 7

        def bind(self, address: object) -> None:
            self.bound = address

    @pytest.mark.parametrize("version", [(3, 10, 14), (3, 11, 2), (3, 12, 9)])
    def test_binds_a_zeroed_address_through_libc_without_the_fix(
        self, version: tuple[int, int, int]
    ):
        sock = self._Sock()
        calls: list[tuple[int, bytes, int]] = []

        def libc_bind(fd: int, addr: bytes, length: int) -> int:
            calls.append((fd, addr, length))
            return 0

        bind_hci(sock, 1, version=version, libc_bind=libc_bind)  # type: ignore[arg-type]

        # sockaddr_hci { AF_BLUETOOTH, dev 1, channel 0 (raw) }
        assert calls == [(7, bytes.fromhex("1f0001000000"), 6)]
        assert sock.bound is None

    @pytest.mark.parametrize("version", [(3, 12, 10), (3, 13, 3), (3, 14, 0)])
    def test_binds_through_python_with_the_fix(self, version: tuple[int, int, int]):
        sock = self._Sock()

        bind_hci(sock, 0, version=version, libc_bind=None)  # type: ignore[arg-type]

        assert sock.bound == (0,)

    def test_a_failed_libc_bind_raises_oserror(self):
        with pytest.raises(OSError):
            bind_hci(
                self._Sock(),  # type: ignore[arg-type]
                0,
                version=(3, 11, 0),
                libc_bind=lambda fd, addr, length: -1,
            )
