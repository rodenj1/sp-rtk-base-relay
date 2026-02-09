"""Bluetooth device manager using BlueZ D-Bus API.

This module provides a Python wrapper around the BlueZ D-Bus API for managing
Bluetooth device discovery, pairing, trusting, and connection operations.

Uses dbus-fast for modern, type-safe D-Bus communication with full type hints.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dbus_fast import BusType, DBusError
    from dbus_fast.aio import MessageBus as AioMessageBus
    from dbus_fast.introspection import Node
    from dbus_fast.proxy_object import ProxyInterface

try:
    from dbus_fast import BusType, DBusError
    from dbus_fast.aio import MessageBus as AioMessageBus
    from dbus_fast.introspection import Node
    from dbus_fast.proxy_object import ProxyInterface
    
    _dbus_fast_available = True
except ImportError:
    _dbus_fast_available = False

logger = logging.getLogger(__name__)


class BluetoothError(Exception):
    """Bluetooth-specific errors."""

    pass


class BluetoothManager:
    """Manages Bluetooth device operations via BlueZ D-Bus API.

    This class provides methods for device discovery, pairing, trusting,
    and connection management using the BlueZ Bluetooth stack through D-Bus.

    Uses dbus-fast with a sync wrapper pattern for easy integration while
    maintaining full type safety and performance.

    Attributes:
        adapter_path: D-Bus object path for the adapter (e.g., "/org/bluez/hci0")
        _bus: Async D-Bus system bus connection
        _adapter: Bluetooth adapter proxy interface
        _introspection_cache: Cache of introspection XML by object path
    """

    def __init__(self, adapter_name: str = "hci0"):
        """Initialize Bluetooth manager.

        Args:
            adapter_name: Name of Bluetooth adapter (default: "hci0")

        Raises:
            BluetoothError: If dbus-fast is not available or adapter not found
        """
        if not _dbus_fast_available:
            raise BluetoothError(
                "dbus-fast library not available. Install with: uv add dbus-fast"
            )

        self.adapter_path = f"/org/bluez/{adapter_name}"
        self._bus: "AioMessageBus | None" = None
        self._adapter: "ProxyInterface | None" = None
        
        # Hybrid introspection cache: pre-cache adapter/root, lazy-cache devices
        self._introspection_cache: dict[str, "Node"] = {}

        self._init_bus()

    def _init_bus(self) -> None:
        """Initialize D-Bus connection and cache adapter introspection.

        This runs synchronously using asyncio.run() to maintain a simple API.
        Pre-caches introspection for adapter and root paths.
        """

        async def _async_init() -> None:
            try:
                # Connect to system bus
                self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()  # type: ignore[misc]

                # Pre-cache adapter and root introspection (these never change)
                adapter_intro = await self._get_introspection(self.adapter_path)
                await self._get_introspection("/")  # Pre-cache root

                # Get adapter proxy interface
                adapter_proxy = self._bus.get_proxy_object(
                    "org.bluez", self.adapter_path, adapter_intro
                )
                self._adapter = adapter_proxy.get_interface("org.bluez.Adapter1")  # type: ignore[arg-type]

                logger.info(
                    f"Initialized Bluetooth manager with adapter {self.adapter_path}"
                )

            except DBusError as e:
                raise BluetoothError(f"D-Bus error initializing adapter: {e}")
            except Exception as e:
                raise BluetoothError(f"Failed to initialize Bluetooth adapter: {e}")

        try:
            asyncio.run(_async_init())
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Failed to initialize async bus: {e}")

    async def _get_introspection(self, path: str) -> "Node":
        """Get introspection with caching (hybrid approach).

        Args:
            path: D-Bus object path

        Returns:
            Introspection Node object

        Raises:
            BluetoothError: If introspection fails
        """
        if path not in self._introspection_cache:
            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")
                introspection: Node = await self._bus.introspect("org.bluez", path)  # type: ignore[assignment]
                self._introspection_cache[path] = introspection
            except DBusError as e:
                raise BluetoothError(f"D-Bus error introspecting {path}: {e}")
            except Exception as e:
                raise BluetoothError(f"Failed to introspect {path}: {e}")

        return self._introspection_cache[path]

    def find_device_by_name(
        self, device_name: str, scan_timeout: int = 10
    ) -> str | None:
        """Scan for device by name and return MAC address.

        Args:
            device_name: Bluetooth device name to search for
            scan_timeout: How long to scan in seconds (default: 10)

        Returns:
            MAC address if found, None otherwise

        Raises:
            BluetoothError: If scanning fails
        """

        async def _async_impl() -> str | None:
            try:
                if self._adapter is None:
                    raise BluetoothError("Adapter not initialized")

                logger.info(f"Scanning for device: {device_name}")

                # Start discovery
                await self._adapter.call_start_discovery()  # type: ignore[attr-defined]

                # Wait for scan
                await asyncio.sleep(scan_timeout)

                # Get object manager to enumerate all Bluetooth objects
                root_intro = await self._get_introspection("/")
                manager_proxy = self._bus.get_proxy_object("org.bluez", "/", root_intro)  # type: ignore[union-attr]
                manager = manager_proxy.get_interface("org.freedesktop.DBus.ObjectManager")

                objects: dict[str, dict[str, Any]] = await manager.call_get_managed_objects()  # type: ignore[attr-defined]

                # Search through discovered devices
                for _path, interfaces in objects.items():
                    if "org.bluez.Device1" in interfaces:
                        device_props = interfaces["org.bluez.Device1"]
                        if device_props.get("Name") == device_name:
                            mac_address = device_props.get("Address")
                            logger.info(f"Found {device_name} at {mac_address}")
                            await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
                            return mac_address

                await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
                logger.warning(f"Device {device_name} not found")
                return None

            except DBusError as e:
                try:
                    if self._adapter is not None:
                        await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
                except Exception:
                    pass
                raise BluetoothError(f"D-Bus error during discovery: {e}")
            except BluetoothError:
                raise
            except Exception as e:
                try:
                    if self._adapter is not None:
                        await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
                except Exception:
                    pass
                raise BluetoothError(f"Device discovery failed: {e}")

        return asyncio.run(_async_impl())

    def find_device_by_mac(self, mac_address: str) -> bool:
        """Check if device with MAC address exists/is known.

        Args:
            mac_address: Device MAC address (e.g., "00:11:22:33:44:55")

        Returns:
            True if device exists, False otherwise
        """

        async def _async_impl() -> bool:
            device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

            try:
                if self._bus is None:
                    return False
                await self._get_introspection(device_path)
                return True
            except Exception:
                return False

        return asyncio.run(_async_impl())

    def pair_device(self, mac_address: str, pin: str = "0000") -> bool:
        """Pair with a Bluetooth device.

        Args:
            mac_address: Device MAC address
            pin: PIN code for pairing (default: "0000")

        Returns:
            True if paired successfully

        Raises:
            BluetoothError: If pairing fails
        """

        async def _async_impl() -> bool:
            device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")

                # Get device introspection and proxy
                device_intro = await self._get_introspection(device_path)
                device_proxy = self._bus.get_proxy_object(
                    "org.bluez", device_path, device_intro
                )
                device_iface = device_proxy.get_interface("org.bluez.Device1")
                device_props = device_proxy.get_interface(
                    "org.freedesktop.DBus.Properties"
                )

                # Check if already paired
                paired: bool = await device_props.call_get("org.bluez.Device1", "Paired")  # type: ignore[attr-defined]
                if paired:
                    logger.info(f"Device {mac_address} already paired")
                    return True

                logger.info(f"Pairing with {mac_address}...")
                await device_iface.call_pair()  # type: ignore[attr-defined]
                logger.info(f"Successfully paired with {mac_address}")
                return True

            except DBusError as e:
                raise BluetoothError(f"D-Bus error during pairing: {e}")
            except BluetoothError:
                raise
            except Exception as e:
                raise BluetoothError(f"Pairing failed: {e}")

        return asyncio.run(_async_impl())

    def trust_device(self, mac_address: str) -> bool:
        """Trust a device so it can auto-reconnect.

        Args:
            mac_address: Device MAC address

        Returns:
            True if trusted successfully

        Raises:
            BluetoothError: If trust operation fails
        """

        async def _async_impl() -> bool:
            device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")

                # Get device introspection and proxy
                device_intro = await self._get_introspection(device_path)
                device_proxy = self._bus.get_proxy_object(
                    "org.bluez", device_path, device_intro
                )
                device_props = device_proxy.get_interface(
                    "org.freedesktop.DBus.Properties"
                )

                # Set Trusted property
                await device_props.call_set("org.bluez.Device1", "Trusted", ("b", True))  # type: ignore[attr-defined]
                logger.info(f"Device {mac_address} is now trusted")
                return True

            except DBusError as e:
                raise BluetoothError(f"D-Bus error setting trust: {e}")
            except BluetoothError:
                raise
            except Exception as e:
                raise BluetoothError(f"Trust failed: {e}")

        return asyncio.run(_async_impl())

    def connect_device(
        self, mac_address: str, max_retries: int = 3, retry_delay: float = 2.0
    ) -> bool:
        """Connect to a paired Bluetooth device with retries.

        Args:
            mac_address: Device MAC address
            max_retries: Maximum connection attempts (default: 3)
            retry_delay: Seconds to wait between retries (default: 2.0)

        Returns:
            True if connected successfully

        Raises:
            BluetoothError: If all connection attempts fail
        """

        async def _async_impl() -> bool:
            device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")

                # Get device introspection and proxy
                device_intro = await self._get_introspection(device_path)
                device_proxy = self._bus.get_proxy_object(
                    "org.bluez", device_path, device_intro
                )
                device_iface = device_proxy.get_interface("org.bluez.Device1")
                device_props = device_proxy.get_interface(
                    "org.freedesktop.DBus.Properties"
                )

                # Check if already connected
                connected: bool = await device_props.call_get("org.bluez.Device1", "Connected")  # type: ignore[attr-defined]
                if connected:
                    logger.info(f"Device {mac_address} already connected")
                    return True

                # Try connecting with retries
                last_error: DBusError | None = None
                for attempt in range(1, max_retries + 1):
                    try:
                        logger.info(
                            f"Connecting to {mac_address} (attempt {attempt}/{max_retries})..."
                        )
                        await device_iface.call_connect()  # type: ignore[attr-defined]
                        logger.info(f"Successfully connected to {mac_address}")
                        return True
                    except DBusError as e:
                        last_error = e
                        error_str = str(e)

                        # Check for "Operation currently not available" error
                        if (
                            "NotAvailable" in error_str
                            or "not available" in error_str.lower()
                        ):
                            if attempt < max_retries:
                                logger.warning(
                                    f"Device not ready (attempt {attempt}/{max_retries}), "
                                    f"waiting {retry_delay}s before retry..."
                                )
                                await asyncio.sleep(retry_delay)
                                continue

                        # For other errors, don't retry
                        raise BluetoothError(f"D-Bus connection error: {e}")

                # All retries exhausted
                raise BluetoothError(
                    f"Connection failed after {max_retries} attempts: {last_error}"
                )

            except BluetoothError:
                raise
            except Exception as e:
                raise BluetoothError(f"Connection failed: {e}")

        return asyncio.run(_async_impl())

    def disconnect_device(self, mac_address: str) -> bool:
        """Disconnect from a Bluetooth device.

        Args:
            mac_address: Device MAC address

        Returns:
            True if disconnected successfully

        Raises:
            BluetoothError: If disconnection fails
        """

        async def _async_impl() -> bool:
            device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")

                # Get device introspection and proxy
                device_intro = await self._get_introspection(device_path)
                device_proxy = self._bus.get_proxy_object(
                    "org.bluez", device_path, device_intro
                )
                device_iface = device_proxy.get_interface("org.bluez.Device1")

                await device_iface.call_disconnect()  # type: ignore[attr-defined]
                logger.info(f"Disconnected from {mac_address}")
                return True

            except DBusError as e:
                raise BluetoothError(f"D-Bus error during disconnect: {e}")
            except BluetoothError:
                raise
            except Exception as e:
                raise BluetoothError(f"Disconnection failed: {e}")

        return asyncio.run(_async_impl())

    def discover_rfcomm_channel(self, mac_address: str) -> int:
        """Discover the RFCOMM channel for Serial Port Profile (SPP).

        For most GPS devices using SPP, the channel is 1. This method
        provides a way to discover it, but defaults to 1 if not found.

        Args:
            mac_address: Device MAC address

        Returns:
            RFCOMM channel number (usually 1 for SPP)
        """
        # For now, return channel 1 (standard for SPP)
        # UUID for Serial Port Profile: 00001101-0000-1000-8000-00805f9b34fb
        # TODO: Could be enhanced to query SDP for exact channel
        logger.info(f"Using RFCOMM channel 1 for SPP on {mac_address}")
        return 1

    def ensure_device_ready(
        self, device_name: str | None = None, mac_address: str | None = None
    ) -> tuple[str, int]:
        """Ensure device is discovered, paired, trusted, and return connection info.

        This is a convenience method that orchestrates the full device setup workflow.

        Args:
            device_name: Name to search for (e.g., "RTK_GPS_BASE")
            mac_address: Or provide MAC directly if already known

        Returns:
            Tuple of (mac_address, rfcomm_channel)

        Raises:
            BluetoothError: If any step fails
        """
        # Discover device if only name provided
        if mac_address is None and device_name:
            mac_address = self.find_device_by_name(device_name)
            if not mac_address:
                raise BluetoothError(f"Device {device_name} not found")

        if not mac_address:
            raise BluetoothError("Must provide either device_name or mac_address")

        # Ensure paired
        if not self.pair_device(mac_address):
            raise BluetoothError(f"Failed to pair with {mac_address}")

        # Ensure trusted
        if not self.trust_device(mac_address):
            raise BluetoothError(f"Failed to trust {mac_address}")

        # NOTE: We do NOT call connect_device() for SPP (Serial Port Profile) devices!
        # SPP devices (like GPS receivers) reject D-Bus Connect() calls with NotAvailable error.
        # This is normal/expected behavior - the RFCOMM socket connection itself establishes
        # the Bluetooth connection. This matches how the old rfcomm tool worked.
        logger.info(
            f"Device {mac_address} is paired and trusted, ready for RFCOMM socket connection"
        )

        # Get RFCOMM channel
        channel = self.discover_rfcomm_channel(mac_address)

        logger.info(f"Device {mac_address} ready on channel {channel}")
        return mac_address, channel
