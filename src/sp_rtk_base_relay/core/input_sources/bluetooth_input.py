"""Bluetooth input source for GNSS receivers.

This module provides a Bluetooth input source implementation for reading
RTCM correction data from GNSS receivers via Bluetooth SPP (Serial Port Profile).
Uses native BlueZ D-Bus API via dbus-fast and native Python Bluetooth sockets.
"""

import logging
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...exceptions import InputSourceError
from ..bluetooth_manager import BluetoothError, BluetoothManager
from .base_input import InputSource

# Bluetooth socket constants (Linux-only)
if TYPE_CHECKING:
    AF_BLUETOOTH: int = getattr(socket, "AF_BLUETOOTH", 31)
    BTPROTO_RFCOMM: int = getattr(socket, "BTPROTO_RFCOMM", 3)
else:
    AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
    BTPROTO_RFCOMM = getattr(socket, "BTPROTO_RFCOMM", 3)

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

            # Ensure device is ready (discover, pair, trust, connect via D-Bus).
            # ``scan_timeout`` bounds how long we'll wait for BlueZ to
            # populate ``org.bluez.Device1`` on the device path — the
            # interface gets stripped ~30 s after RFCOMM close on
            # ZED-F9P and a fixed 5 s scan in v2.1.2 was not enough
            # for BlueZ's two-phase rediscovery to restore it.
            try:
                mac, channel = self.bt_manager.ensure_device_ready(
                    pin=self.config.pin,
                    device_name=self.config.device_name,
                    mac_address=self.config.mac_address,
                    scan_timeout=self.config.scan_timeout,
                )
                self.connected_mac = mac
                self.rfcomm_channel = channel
                logger.info(f"Bluetooth device ready: {mac} on channel {channel}")
            except BluetoothError as e:
                raise InputSourceError(f"Failed to prepare Bluetooth device: {e}")

            # Create native Bluetooth socket for data transfer
            try:
                logger.info(
                    f"Creating native Bluetooth socket for {self.connected_mac}:{self.rfcomm_channel}"
                )

                # Create AF_BLUETOOTH socket
                self.bt_socket = socket.socket(
                    AF_BLUETOOTH,  # type: ignore[arg-type]
                    socket.SOCK_STREAM,
                    BTPROTO_RFCOMM,  # type: ignore[arg-type]
                )
                self.bt_socket.settimeout(self.config.connect_timeout)

                # Connect to device
                self.bt_socket.connect((self.connected_mac, self.rfcomm_channel))

                # Set read timeout
                self.bt_socket.settimeout(self.config.read_timeout)

                logger.info("Bluetooth socket connected successfully")
            except OSError as e:
                raise InputSourceError(f"Bluetooth socket connection failed: {e}")
            except Exception as e:
                raise InputSourceError(f"Unexpected socket error: {e}")

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

        Teardown ordering matters here.  We ask BlueZ to disconnect the
        device **first** (via ``org.bluez.Device1.Disconnect``) and only
        then close our local RFCOMM socket.  This way BlueZ owns the
        teardown of the underlying ACL/RFCOMM channel state — if the
        process is ``SIGKILL``-ed midway through ``disconnect()``, the
        kernel will still tear down our local socket descriptor, but
        BlueZ's view of the device will already be ``Connected=false``
        and the next connect attempt won't have to fight a stale
        half-paired state.

        The previous order — close socket, then ask BlueZ to disconnect
        — could leave BlueZ believing the device was still connected
        after an unclean exit, which manifested as the next startup
        either failing to bind the RFCOMM channel or having to scan +
        re-pair to recover.

        Finally we shut down the ``BluetoothManager``'s background event
        loop so the next ``connect()`` gets a fresh manager with an empty
        introspection cache.

        All three steps are independently wrapped in ``try/except`` so
        no single failure can short-circuit the rest of the cleanup.
        """
        logger.info("Disconnecting from Bluetooth device")

        # Step 1 — ask BlueZ to disconnect the device FIRST so the
        # canonical "Connected" state is updated before we tear down
        # our local handle.
        if self.bt_manager and self.connected_mac:
            try:
                self.bt_manager.disconnect_device(self.connected_mac)
            except Exception as e:
                logger.warning(f"Error disconnecting Bluetooth D-Bus: {e}")

        # Step 2 — close our local RFCOMM socket.  By this point BlueZ
        # has (best-effort) already torn down the underlying channel,
        # so this is effectively releasing our local fd.
        if self.bt_socket:
            try:
                self.bt_socket.close()
            except Exception as e:
                logger.warning(f"Error closing Bluetooth socket: {e}")
            finally:
                self.bt_socket = None

        # Step 3 — release the BluetoothManager's background event loop
        # and D-Bus connection.  The next connect() will create a fresh
        # manager with an empty introspection cache, avoiding stale
        # cache issues.
        if self.bt_manager is not None:
            try:
                self.bt_manager.close()
            except Exception as e:
                logger.warning(f"Error closing BluetoothManager: {e}")
            finally:
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
        """Cleanup resources after connection error."""
        if self.bt_socket:
            try:
                self.bt_socket.close()
            except:
                pass
            self.bt_socket = None

        if self.bt_manager and self.connected_mac:
            try:
                self.bt_manager.disconnect_device(self.connected_mac)
            except:
                pass

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
