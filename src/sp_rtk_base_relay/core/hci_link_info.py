"""Raw-HCI readings for a connected RFCOMM link: Bluetooth link strength.

:func:`read_rssi` asks the adapter for the HCI ``Read RSSI`` of the ACL
connection under an open RFCOMM socket. On a classic (BR/EDR) link, which
RFCOMM always is, the value is a signed dB offset from a range the
controller picks, never dBm: 0 = inside the range, negative = that many dB
below it, positive = above it.

How it works, with no capability or group needed:

- The ACL connection handle comes from the RFCOMM socket itself, through
  ``getsockopt(SOL_RFCOMM, RFCOMM_CONNINFO)``.
- A short-lived raw HCI socket is bound to the adapter on the raw channel
  and sends ``Read RSSI``. The kernel lets any user send it (it is on the
  raw socket security filter's whitelist) while ``bluetoothd`` owns the
  adapter. The socket is closed after each reading, because a bound raw
  socket keeps the adapter in promiscuous delivery while it stays open.

The read is bounded by a timeout and never raises: any failure (``ENOTCONN``
from a link torn down mid-read, an HCI error status, the adapter's 127
"unavailable", no reply in time) reads as ``None``.

Bluetooth sockets are refused in a separate network namespace, so the
service must never run with systemd's ``PrivateNetwork=yes``.
"""

from __future__ import annotations

import ctypes
import os
import re
import socket
import struct
import sys
import time
from collections.abc import Callable
from typing import Final

# Bluetooth socket constants (Linux-only), with the kernel's values as
# fallbacks so the module imports everywhere.
AF_BLUETOOTH: Final[int] = getattr(socket, "AF_BLUETOOTH", 31)
BTPROTO_HCI: Final[int] = getattr(socket, "BTPROTO_HCI", 1)
SOL_HCI: Final[int] = getattr(socket, "SOL_HCI", 0)
HCI_FILTER: Final[int] = getattr(socket, "HCI_FILTER", 2)
SOL_RFCOMM: Final[int] = 18
RFCOMM_CONNINFO: Final[int] = 2

HCI_COMMAND_PKT: Final[int] = 0x01
HCI_EVENT_PKT: Final[int] = 0x04
EVT_CMD_COMPLETE: Final[int] = 0x0E
EVT_CMD_STATUS: Final[int] = 0x0F
OP_READ_RSSI: Final[int] = 0x1405  # OGF 0x05 (status parameters), OCF 0x0005
RSSI_UNAVAILABLE: Final[int] = 127

# The longest a reading may hold up whoever builds the status.
READ_RSSI_TIMEOUT: Final[float] = 0.5

HciSocketFactory = Callable[[int], socket.socket]
"""Opens a raw HCI socket bound to the adapter with the given index."""


def hci_socket(adapter_index: int) -> socket.socket:
    """Open a raw HCI socket bound to an adapter on the raw channel."""
    sock = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    try:
        bind_hci(sock, adapter_index)
    except BaseException:
        sock.close()
        raise
    return sock


def bind_hci(
    sock: socket.socket,
    adapter_index: int,
    *,
    version: tuple[int, int, int] | None = None,
    libc_bind: Callable[[int, bytes, int], int] | None = None,
) -> None:
    """Bind a raw HCI socket to an adapter on ``HCI_CHANNEL_RAW``.

    CPython's ``bind((dev,))`` for ``BTPROTO_HCI`` left the address's
    channel field uninitialised (cpython#132075), so the bind could fail
    or land on the wrong channel. The fix shipped in 3.12.10 and 3.13.3.
    On any earlier interpreter the socket is bound through libc with a
    zeroed ``sockaddr_hci`` instead.

    Args:
        sock: An unbound raw HCI socket.
        adapter_index: The adapter's index (0 for ``hci0``).
        version: The interpreter version to act for (defaults to the
            running one).
        libc_bind: libc's ``bind(fd, addr, len)`` (defaults to the real one).
    """
    if not needs_zeroed_bind(version or sys.version_info[:3]):
        sock.bind((adapter_index,))
        return
    # struct sockaddr_hci { sa_family_t family; u16 dev; u16 channel; }
    addr = struct.pack("<HHH", AF_BLUETOOTH, adapter_index, 0)
    if libc_bind is None:
        libc = ctypes.CDLL(None, use_errno=True)
        libc_bind = libc.bind
    if libc_bind(sock.fileno(), addr, len(addr)) != 0:
        err = ctypes.get_errno()
        raise OSError(err, f"bind(HCI dev {adapter_index}): {os.strerror(err)}")


def needs_zeroed_bind(version: tuple[int, int, int]) -> bool:
    """Whether this CPython version lacks the cpython#132075 fix."""
    if version >= (3, 14, 0):
        return False
    if version[:2] == (3, 13):
        return version < (3, 13, 3)
    return version < (3, 12, 10)


def adapter_index(adapter_name: str) -> int | None:
    """The index of an adapter named like ``hci0``, or None for any other name."""
    match = re.fullmatch(r"hci(\d+)", adapter_name)
    return int(match.group(1)) if match else None


def read_rssi(
    rfcomm_socket: socket.socket,
    adapter: int,
    *,
    timeout: float = READ_RSSI_TIMEOUT,
    socket_factory: HciSocketFactory = hci_socket,
    monotonic: Callable[[], float] = time.monotonic,
) -> int | None:
    """Read the link's RSSI from the adapter. Never raises.

    Args:
        rfcomm_socket: The connected RFCOMM socket whose link to read.
        adapter: The index of the adapter the link runs over.
        timeout: The longest to wait for the adapter's reply, in seconds.
        socket_factory: Opens the raw HCI socket bound to the adapter.
        monotonic: The clock the timeout is measured on.

    Returns:
        The relative dB the adapter reports, or None when there's no
        reading: the link is down, the adapter answers 127 or an error
        status, any socket call fails, or no reply arrives in time.
    """
    try:
        deadline = monotonic() + timeout
        conninfo = rfcomm_socket.getsockopt(SOL_RFCOMM, RFCOMM_CONNINFO, 6)
        handle: int = struct.unpack_from("<H", conninfo)[0]
        sock = socket_factory(adapter)
        try:
            return _ask_rssi(sock, handle, deadline, monotonic)
        finally:
            sock.close()
    except Exception:
        return None


def _ask_rssi(
    sock: socket.socket,
    handle: int,
    deadline: float,
    monotonic: Callable[[], float],
) -> int | None:
    # struct hci_filter { u32 type_mask; u32 event_mask[2]; u16 opcode; }
    event_mask = (1 << EVT_CMD_COMPLETE) | (1 << EVT_CMD_STATUS)
    hci_filter = struct.pack("<IIIH", 1 << HCI_EVENT_PKT, event_mask, 0, OP_READ_RSSI)
    sock.setsockopt(SOL_HCI, HCI_FILTER, hci_filter)
    sock.send(struct.pack("<BHBH", HCI_COMMAND_PKT, OP_READ_RSSI, 2, handle))
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return None
        sock.settimeout(remaining)
        answered, rssi = _parse_reply(sock.recv(260), handle)
        if answered:
            return rssi


def _parse_reply(packet: bytes, handle: int) -> tuple[bool, int | None]:
    """Whether a packet answers our Read RSSI, and the reading if it does."""
    if len(packet) < 3 or packet[0] != HCI_EVENT_PKT:
        return False, None
    event = packet[1]
    if event == EVT_CMD_STATUS and len(packet) >= 7:
        # 04 0F plen status ncmd opcode(2)
        status, _, opcode = struct.unpack_from("<BBH", packet, 3)
        return (opcode == OP_READ_RSSI and status != 0), None
    if event == EVT_CMD_COMPLETE and len(packet) >= 7:
        # 04 0E plen ncmd opcode(2) status [handle(2) rssi(s8)]
        opcode, status = struct.unpack_from("<HB", packet, 4)
        if opcode != OP_READ_RSSI:
            return False, None
        if status != 0:
            return True, None
        if len(packet) < 10:
            return True, None
        reply_handle, rssi = struct.unpack_from("<Hb", packet, 7)
        if reply_handle & 0x0FFF != handle & 0x0FFF:
            return False, None
        return True, (None if rssi == RSSI_UNAVAILABLE else rssi)
    return False, None
