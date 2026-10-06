"""The shared RFCOMM link helper: one place for the Bluetooth open and teardown.

Opening and closing an RFCOMM link to a Bluetooth SPP module is order
sensitive, and three callers need it: the Relay's Bluetooth input,
sp-rtk-base's Bluetooth Verification and its Bluetooth console link. This
module is the one place that order lives.

- :func:`open_rfcomm_link` prepares the device through a
  :class:`BluetoothManager` (pairing with the PIN when there's no Bond),
  then connects an ``AF_BLUETOOTH``/``BTPROTO_RFCOMM`` socket within the
  config's ``connect_timeout``. A socket reopened straight after a close
  can return ``EBUSY``, so that error is retried for a short, bounded time.
- :meth:`RfcommLink.close` tears down in sp-rtk-base ADR 0002's order:
  ``Device1.Disconnect``, then the socket, then ``manager.close()``. Each
  step is wrapped, so no failure skips the rest.

The caller creates the manager and hands it in, and the link owns it from
then on: closing the link closes the manager last.
"""

from __future__ import annotations

import errno
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bluetooth_manager import BluetoothManager
    from .input_sources.bluetooth_input import BluetoothConfig

# Bluetooth socket constants (Linux-only).
if TYPE_CHECKING:
    AF_BLUETOOTH: int = getattr(socket, "AF_BLUETOOTH", 31)
    BTPROTO_RFCOMM: int = getattr(socket, "BTPROTO_RFCOMM", 3)
else:
    AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
    BTPROTO_RFCOMM = getattr(socket, "BTPROTO_RFCOMM", 3)

logger = logging.getLogger(__name__)

# How long a connect that returns EBUSY is retried, and the pause between
# attempts. A reopen straight after a close returns EBUSY on the bench
# while the kernel finishes releasing the previous RFCOMM channel.
BUSY_RETRY_FOR = 3.0
BUSY_RETRY_INTERVAL = 0.25


def rfcomm_socket() -> socket.socket:
    """Create an unconnected ``AF_BLUETOOTH``/``BTPROTO_RFCOMM`` stream socket."""
    return socket.socket(
        AF_BLUETOOTH,
        socket.SOCK_STREAM,
        BTPROTO_RFCOMM,
    )


class RfcommConnectError(Exception):
    """The RFCOMM socket could not be connected.

    Raised by :func:`open_rfcomm_link` after the device was prepared, so a
    caller can tell a connect failure apart from a preparation failure
    (which surfaces as :class:`BluetoothError`). The underlying ``OSError``
    is the ``__cause__``.
    """


@dataclass
class RfcommLink:
    """An open RFCOMM link: the connected socket and the manager that owns it."""

    manager: BluetoothManager
    socket: socket.socket
    mac: str
    channel: int

    def close(self) -> None:
        """Tear the link down in sp-rtk-base ADR 0002's order. Never raises.

        ``Device1.Disconnect`` goes first, so BlueZ's ``Connected`` state is
        already false if the process dies part-way through. Then the socket
        is closed, and the manager last, so the next open gets a fresh
        manager. Each step is wrapped so no failure skips the rest.
        """
        _disconnect_device(self.manager, self.mac)
        _close_socket(self.socket)
        try:
            self.manager.close()
        except Exception as e:
            logger.warning(f"Error closing BluetoothManager: {e}")


def open_rfcomm_link(
    manager: BluetoothManager,
    config: BluetoothConfig,
    *,
    busy_retry_for: float = BUSY_RETRY_FOR,
    busy_retry_interval: float = BUSY_RETRY_INTERVAL,
    socket_factory: Callable[[], socket.socket] = rfcomm_socket,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> RfcommLink:
    """Prepare the device and connect an RFCOMM socket to it."""
    mac, channel = manager.ensure_device_ready(
        pin=config.pin,
        device_name=config.device_name,
        mac_address=config.mac_address,
        scan_timeout=config.scan_timeout,
    )
    deadline = monotonic() + busy_retry_for
    while True:
        sock = socket_factory()
        try:
            sock.settimeout(config.connect_timeout)
            sock.connect((mac, channel))
        except Exception as e:
            busy = isinstance(e, OSError) and e.errno == errno.EBUSY
            if busy and monotonic() < deadline:
                logger.debug(f"RFCOMM {mac}:{channel} busy, retrying")
                _close_socket(sock)
                sleep(busy_retry_interval)
                continue
            # Leave BlueZ as a clean close would, but keep the manager:
            # the caller created it and may retry with it.
            _disconnect_device(manager, mac)
            _close_socket(sock)
            if busy:
                raise RfcommConnectError(
                    f"RFCOMM channel {channel} on {mac} still busy "
                    f"after {busy_retry_for:g} s: {e}"
                ) from e
            raise RfcommConnectError(
                f"RFCOMM connect to {mac} channel {channel} failed: {e}"
            ) from e
        sock.settimeout(config.read_timeout)
        return RfcommLink(manager=manager, socket=sock, mac=mac, channel=channel)


def _disconnect_device(manager: BluetoothManager, mac: str) -> None:
    try:
        manager.disconnect_device(mac)
    except Exception as e:
        logger.warning(f"Error disconnecting Bluetooth D-Bus: {e}")


def _close_socket(sock: socket.socket) -> None:
    try:
        sock.close()
    except Exception as e:
        logger.warning(f"Error closing Bluetooth socket: {e}")
