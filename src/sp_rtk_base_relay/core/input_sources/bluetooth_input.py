"""Bluetooth input source for GNSS receivers.

This module provides a Bluetooth input source implementation for reading
RTCM correction data from GNSS receivers via Bluetooth SPP (Serial Port Profile).
Uses native BlueZ D-Bus API via dbus-fast and native Python Bluetooth sockets.
"""

import logging
import socket
from dataclasses import dataclass
from typing import Any

from ...exceptions import InputSourceError
from ..bluetooth_manager import BluetoothError, BluetoothManager
from ..rfcomm_link import (
    AF_BLUETOOTH,
    BTPROTO_RFCOMM,
    RfcommConnectError,
    RfcommLink,
    open_rfcomm_link,
)
from .base_input import InputSource

# Re-exported: integrators import the socket constants from here.
__all__ = [
    "AF_BLUETOOTH",
    "BTPROTO_RFCOMM",
    "BluetoothConfig",
    "BluetoothInputSource",
]

logger = logging.getLogger(__name__)


@dataclass
class BluetoothConfig:
    """Bluetooth configuration parameters."""

    device_name: str | None = None  # e.g., "RTK_GPS_BASE" - for auto-discovery
    mac_address: str | None = None  # e.g., "00:11:22:33:44:55" - if known
    auto_pair: bool = True  # Automatically pair if not paired
    auto_trust: bool = True  # Automatically trust device
    pin: str = "0000"  # PIN code for pairing
    adapter_name: str = "hci0"  # Bluetooth adapter to use
    # Device discovery + Device1 interface-population timeout (seconds).
    # Bumped from 10 -> 30 in v2.1.3: BlueZ strips org.bluez.Device1 from
    # the device path ~30 s after RFCOMM close, and its two-phase
    # rediscovery sometimes needs 20+ seconds of active scanning to
    # repopulate the interface.  The poll loop in
    # ``BluetoothManager._async_wait_for_device_interface`` returns
    # early as soon as the interface appears, so the 30 s ceiling is
    # zero-overhead when the device is already known to BlueZ.
    scan_timeout: int = 30
    read_timeout: float = 1.0  # Socket read timeout
    connect_timeout: float = 10.0  # Connection timeout


class BluetoothInputSource(InputSource):
    """Bluetooth input source for GNSS receivers.

    Provides RTCM data reading from GNSS receivers connected via Bluetooth SPP.
    Handles device discovery, pairing, trusting, and connection automatically.
    Uses native BlueZ D-Bus API and AF_BLUETOOTH sockets - no rfcomm required.
    """

    def __init__(self, config: BluetoothConfig):
        """Initialize Bluetooth input source.

        Args:
            config: Bluetooth configuration

        Raises:
            InputSourceError: If configuration is invalid
        """
        super().__init__("Bluetooth")
        self.config = config
        self.bt_manager: BluetoothManager | None = None
        self.bt_socket: socket.socket | None = None
        self.connected_mac: str | None = None
        self.rfcomm_channel: int | None = None
        self._link: RfcommLink | None = None

        # Validate configuration
        self._validate_config()

        logger.info(
            f"Initialized Bluetooth input source: "
            f"device={config.device_name or config.mac_address}"
        )

    def connect(self) -> bool:
        """Connect to Bluetooth device.

        Performs device discovery (if needed), pairing, trusting, and socket connection.

        Returns:
            True if connection successful

        Raises:
            InputSourceError: If connection fails
        """
        if self.is_connected:
            logger.debug("Bluetooth device already connected")
            return True

        try:
            logger.info("Connecting to Bluetooth device")

            # Initialize Bluetooth manager
            if self.bt_manager is None:
                try:
                    # The relay is the process that should hold BlueZ's
                    # default pairing agent on its own machine, so a
                    # caller-less pairing (see CONTEXT.md) still reaches
                    # someone who knows the PIN -- unlike a throwaway
                    # BluetoothManager an integrator (e.g. sp-rtk-base)
                    # might construct for a UI scan.
                    self.bt_manager = BluetoothManager(
                        adapter_name=self.config.adapter_name,
                        claim_default_agent=True,
                    )
                except BluetoothError as e:
                    raise InputSourceError(f"Failed to initialize Bluetooth: {e}")

            # Prepare the device (discover, pair, trust) and connect the
            # RFCOMM socket through the shared helper, which owns the
            # connect timeout and the brief retry on EBUSY.
            # ``scan_timeout`` bounds how long we'll wait for BlueZ to
            # populate ``org.bluez.Device1`` on the device path.
            try:
                link = open_rfcomm_link(self.bt_manager, self.config)
            except BluetoothError as e:
                raise InputSourceError(f"Failed to prepare Bluetooth device: {e}")
            except RfcommConnectError as e:
                raise InputSourceError(f"Bluetooth socket connection failed: {e}")

            self._link = link
            self.bt_socket = link.socket
            self.connected_mac = link.mac
            self.rfcomm_channel = link.channel
            logger.info(
                f"Bluetooth socket connected to {link.mac} on channel {link.channel}"
            )

            self._update_connection_stats(True)
            return True

        except InputSourceError:
            self._cleanup_on_error()
            self._update_connection_stats(False)
            raise
        except Exception as e:
            error = InputSourceError(f"Unexpected Bluetooth connection error: {e}")
            self._cleanup_on_error()
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read RTCM data from Bluetooth device.

        Args:
            timeout: Read timeout in seconds (uses config default if None)

        Returns:
            Raw RTCM data bytes if available, None if no data or error
        """
        if not self.is_connected or not self.bt_socket:
            return None

        try:
            # BlueDot's recv() handles timeouts internally
            # Try to receive data (up to 8KB)
            data = self.bt_socket.recv(8192)

            if data:
                self._update_read_stats(data)
                logger.debug(f"Read {len(data)} bytes from Bluetooth")
                return data
            else:
                # Empty data means socket closed by remote
                logger.warning("Bluetooth socket closed by remote device")
                self._set_error_state(InputSourceError("Connection closed by device"))
                return None

        except TimeoutError:
            # Timeout is normal - no data available
            self._update_read_stats(None)
            return None
        except OSError as e:
            error = InputSourceError(f"Bluetooth read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None
        except Exception as e:
            error = InputSourceError(f"Unexpected Bluetooth read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None

    def disconnect(self) -> None:
        """Disconnect from Bluetooth device and cleanup resources.

        The RFCOMM link helper tears down in sp-rtk-base ADR 0002's order:
        ``Device1.Disconnect`` first, so BlueZ's view is already
        ``Connected=false`` if the process dies part-way, then the socket,
        then the ``BluetoothManager``, so the next ``connect()`` gets a fresh
        manager. Each step is wrapped so no failure skips the rest.
        """
        logger.info("Disconnecting from Bluetooth device")

        if self._link is not None:
            self._link.close()
        elif self.bt_manager is not None:
            # A manager with no open link (a connect that failed after the
            # manager was built): only the manager is left to release.
            try:
                self.bt_manager.close()
            except Exception as e:
                logger.warning(f"Error closing BluetoothManager: {e}")

        self._link = None
        self.bt_socket = None
        self.bt_manager = None
        self.connected_mac = None
        self.rfcomm_channel = None
        self._connected = False
        self.stats.connected_since = None
        logger.info("Bluetooth device disconnected")

    def get_connection_info(self) -> dict[str, Any]:
        """Get Bluetooth connection information.

        Returns:
            Dictionary with Bluetooth connection details
        """
        info: dict[str, Any] = {
            "device_name": self.config.device_name,
            "mac_address": self.config.mac_address or self.connected_mac,
            "adapter": self.config.adapter_name,
        }

        if self.is_connected:
            info.update(
                {
                    "connected_mac": self.connected_mac,
                    "rfcomm_channel": self.rfcomm_channel,
                    "socket_connected": self.bt_socket is not None,
                }
            )

        return info

    def _validate_config(self) -> None:
        """Validate Bluetooth configuration.

        Raises:
            InputSourceError: If configuration is invalid
        """
        if not self.config.device_name and not self.config.mac_address:
            raise InputSourceError(
                "Either device_name or mac_address must be specified"
            )

        if self.config.scan_timeout <= 0:
            raise InputSourceError(f"Invalid scan timeout: {self.config.scan_timeout}")

        if self.config.read_timeout <= 0:
            raise InputSourceError(f"Invalid read timeout: {self.config.read_timeout}")

        if self.config.connect_timeout <= 0:
            raise InputSourceError(
                f"Invalid connect timeout: {self.config.connect_timeout}"
            )

    def _cleanup_on_error(self) -> None:
        """Reset link state after a failed connect.

        The RFCOMM helper has already disconnected the device and closed
        any socket it opened. The manager is kept for the next attempt.
        """
        self._link = None
        self.bt_socket = None
        self.connected_mac = None
        self.rfcomm_channel = None

    def get_bluetooth_statistics(self) -> dict[str, Any]:
        """Get detailed Bluetooth statistics and status.

        Returns:
            Dictionary with detailed Bluetooth information
        """
        stats = {
            "config": {
                "device_name": self.config.device_name,
                "mac_address": self.config.mac_address,
                "adapter": self.config.adapter_name,
                "auto_pair": self.config.auto_pair,
                "auto_trust": self.config.auto_trust,
            },
            "connection": {
                "connected": self.is_connected,
                "connected_mac": self.connected_mac,
                "rfcomm_channel": self.rfcomm_channel,
                "connection_attempts": self.stats.connection_attempts,
                "successful_connections": self.stats.successful_connections,
                "connection_failures": self.stats.connection_failures,
                "connected_since": self.stats.connected_since,
            },
            "data_flow": {
                "bytes_read": self.stats.bytes_read,
                "messages_read": self.stats.messages_read,
                "read_errors": self.stats.read_errors,
                "last_read_time": self.stats.last_read_time,
            },
            "last_error": str(self.last_error) if self.last_error else None,
        }

        return stats
