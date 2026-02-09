"""Mock Bluetooth fixtures for testing.

This module provides mock implementations of dbus-fast and D-Bus objects
for testing Bluetooth functionality without requiring actual hardware.
"""

from typing import Any
from unittest.mock import MagicMock


class MockProxyInterface:
    """Mock dbus-fast ProxyInterface with call_* methods."""
    
    def __init__(self, interface_name: str, device_data: dict[str, Any] | None = None):
        self.interface_name = interface_name
        self._device_data = device_data or {}
        self._should_fail: dict[str, bool] = {}
    
    async def call_start_discovery(self) -> None:
        """Mock StartDiscovery method."""
        if self._should_fail.get("start_discovery"):
            raise Exception("Discovery failed")
    
    async def call_stop_discovery(self) -> None:
        """Mock StopDiscovery method."""
        pass
    
    async def call_pair(self) -> None:
        """Mock Pair method."""
        if self._should_fail.get("pair"):
            raise Exception("Pairing failed")
        self._device_data["Paired"] = True
    
    async def call_connect(self) -> None:
        """Mock Connect method."""
        if self._should_fail.get("connect"):
            raise Exception("Connection failed")
        self._device_data["Connected"] = True
    
    async def call_disconnect(self) -> None:
        """Mock Disconnect method."""
        if self._should_fail.get("disconnect"):
            raise Exception("Disconnection failed")
        self._device_data["Connected"] = False
    
    async def call_get(self, interface: str, property_name: str) -> Any:
        """Mock Properties Get method."""
        if interface == "org.bluez.Device1":
            return self._device_data.get(property_name, False)
        return None
    
    async def call_set(self, interface: str, property_name: str, value: tuple[str, Any]) -> None:
        """Mock Properties Set method."""
        if interface == "org.bluez.Device1":
            _, actual_value = value
            self._device_data[property_name] = actual_value
    
    async def call_get_managed_objects(self) -> dict[str, dict[str, Any]]:
        """Mock ObjectManager GetManagedObjects method."""
        # This will be populated by the MockMessageBus
        return self._device_data.get("_managed_objects", {})
    
    def set_should_fail(self, method: str, should_fail: bool = True) -> None:
        """Configure a method to fail for testing."""
        self._should_fail[method] = should_fail


class MockProxyObject:
    """Mock dbus-fast ProxyObject."""
    
    def __init__(self, bus_name: str, path: str, device_data: dict[str, Any] | None = None):
        self.bus_name = bus_name
        self.path = path
        self._device_data = device_data or {}
        self._interfaces: dict[str, MockProxyInterface] = {}
    
    def get_interface(self, interface_name: str) -> MockProxyInterface:
        """Get a mock interface."""
        if interface_name not in self._interfaces:
            self._interfaces[interface_name] = MockProxyInterface(
                interface_name, self._device_data
            )
        return self._interfaces[interface_name]


class MockInterface:
    """Mock introspection Interface object."""
    
    def __init__(self, name: str):
        self.name = name


class MockNode:
    """Mock introspection Node object."""
    
    def __init__(self, path: str):
        self.path = path
        # Add common BlueZ interfaces
        self.interfaces = [
            MockInterface("org.bluez.Adapter1"),
            MockInterface("org.bluez.Device1"),
            MockInterface("org.freedesktop.DBus.Properties"),
            MockInterface("org.freedesktop.DBus.ObjectManager"),
        ]


class MockMessageBus:
    """Mock dbus-fast async MessageBus."""
    
    def __init__(self, bus_type: Any = None):
        self.bus_type = bus_type
        self._devices: dict[str, dict[str, Any]] = {}
        self._introspection_cache: dict[str, MockNode] = {}
        self._should_fail_paths: set[str] = set()
    
    async def connect(self) -> "MockMessageBus":
        """Mock connect method."""
        return self
    
    async def introspect(self, bus_name: str, path: str) -> MockNode:
        """Mock introspect method."""
        if path in self._should_fail_paths:
            raise Exception(f"Introspection failed for {path}")
        
        if path not in self._introspection_cache:
            self._introspection_cache[path] = MockNode(path)
        return self._introspection_cache[path]
    
    def get_proxy_object(
        self, bus_name: str, path: str, introspection: Any
    ) -> MockProxyObject:
        """Get a mock proxy object."""
        if path in self._should_fail_paths:
            raise Exception(f"Failed to get proxy for {path}")
        
        # For ObjectManager (root path), include managed objects
        if path == "/":
            device_data = {"_managed_objects": self._get_managed_objects()}
            return MockProxyObject(bus_name, path, device_data)
        
        # For device paths
        if "/dev_" in path:
            device_data = self._devices.get(path, {})
            return MockProxyObject(bus_name, path, device_data)
        
        # For adapter or other paths
        return MockProxyObject(bus_name, path)
    
    def _get_managed_objects(self) -> dict[str, dict[str, Any]]:
        """Get all managed objects for ObjectManager."""
        objects = {}
        for device_path, device_data in self._devices.items():
            objects[device_path] = {
                "org.bluez.Device1": {
                    "Address": device_data.get("Address", ""),
                    "Name": device_data.get("Name", "Unknown"),
                    "Paired": device_data.get("Paired", False),
                    "Trusted": device_data.get("Trusted", False),
                    "Connected": device_data.get("Connected", False),
                }
            }
        return objects
    
    def add_device(
        self,
        mac_address: str,
        name: str = "Test Device",
        adapter_path: str = "/org/bluez/hci0",
        paired: bool = False,
        trusted: bool = False,
        connected: bool = False
    ) -> None:
        """Add a mock device to the bus."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        self._devices[device_path] = {
            "Address": mac_address,
            "Name": name,
            "Paired": paired,
            "Trusted": trusted,
            "Connected": connected,
        }
    
    def remove_device(self, mac_address: str, adapter_path: str = "/org/bluez/hci0") -> None:
        """Remove a mock device from the bus."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        if device_path in self._devices:
            del self._devices[device_path]
    
    def set_should_fail(self, path: str, should_fail: bool = True) -> None:
        """Configure operations on a path to fail."""
        if should_fail:
            self._should_fail_paths.add(path)
        else:
            self._should_fail_paths.discard(path)
    
    def get_device_data(self, mac_address: str, adapter_path: str = "/org/bluez/hci0") -> dict[str, Any] | None:
        """Get device data for inspection in tests."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        return self._devices.get(device_path)
    
    def clear_all_devices(self) -> None:
        """Remove all mock devices."""
        self._devices.clear()


def create_mock_dbus_fast() -> tuple[MagicMock, type[MockMessageBus], Any]:
    """Create mock dbus-fast module components for testing.
    
    Returns:
        Tuple of (BusType mock, MessageBus class, DBusError class)
    """
    # Mock BusType enum
    mock_bus_type = MagicMock()
    mock_bus_type.SYSTEM = "SYSTEM"
    mock_bus_type.SESSION = "SESSION"
    
    # Mock DBusError class
    class MockDBusError(Exception):
        """Mock D-Bus error."""
        pass
    
    return mock_bus_type, MockMessageBus, MockDBusError


def create_mock_message_bus() -> MockMessageBus:
    """Create a standalone mock MessageBus for testing.
    
    Returns:
        MockMessageBus instance ready for testing
    """
    return MockMessageBus()
