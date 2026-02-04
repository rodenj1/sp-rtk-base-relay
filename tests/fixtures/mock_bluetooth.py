"""Mock Bluetooth fixtures for testing.

This module provides mock implementations of pydbus and D-Bus objects
for testing Bluetooth functionality without requiring actual hardware.
"""

from typing import Any
from unittest.mock import MagicMock, Mock


class MockDBusDevice:
    """Mock D-Bus Bluetooth device object."""
    
    def __init__(
        self,
        mac_address: str,
        name: str = "Test Device",
        paired: bool = False,
        trusted: bool = False,
        connected: bool = False
    ):
        self.Address = mac_address
        self.Name = name
        self.Paired = paired
        self.Trusted = trusted
        self.Connected = connected
        
        self._pair_should_fail = False
        self._connect_should_fail = False
        self._disconnect_should_fail = False
    
    def Pair(self) -> None:
        """Mock pairing method."""
        if self._pair_should_fail:
            raise Exception("Pairing failed")
        self.Paired = True
    
    def Connect(self) -> None:
        """Mock connection method."""
        if self._connect_should_fail:
            raise Exception("Connection failed")
        self.Connected = True
    
    def Disconnect(self) -> None:
        """Mock disconnection method."""
        if self._disconnect_should_fail:
            raise Exception("Disconnection failed")
        self.Connected = False
    
    def set_pair_should_fail(self, should_fail: bool) -> None:
        """Configure pairing to fail for testing."""
        self._pair_should_fail = should_fail
    
    def set_connect_should_fail(self, should_fail: bool) -> None:
        """Configure connection to fail for testing."""
        self._connect_should_fail = should_fail
    
    def set_disconnect_should_fail(self, should_fail: bool) -> None:
        """Configure disconnection to fail for testing."""
        self._disconnect_should_fail = should_fail


class MockDBusAdapter:
    """Mock D-Bus Bluetooth adapter object."""
    
    def __init__(self):
        self._discovery_active = False
        self._discovery_should_fail = False
    
    def StartDiscovery(self) -> None:
        """Mock start discovery method."""
        if self._discovery_should_fail:
            raise Exception("Discovery failed")
        self._discovery_active = True
    
    def StopDiscovery(self) -> None:
        """Mock stop discovery method."""
        self._discovery_active = False
    
    def set_discovery_should_fail(self, should_fail: bool) -> None:
        """Configure discovery to fail for testing."""
        self._discovery_should_fail = should_fail
    
    @property
    def is_discovering(self) -> bool:
        """Check if discovery is active."""
        return self._discovery_active


class MockObjectManager:
    """Mock D-Bus ObjectManager."""
    
    def __init__(self):
        self._devices: dict[str, MockDBusDevice] = {}
    
    def GetManagedObjects(self) -> dict[str, dict[str, Any]]:
        """Return mock managed objects."""
        objects = {}
        
        for device_path, device in self._devices.items():
            objects[device_path] = {
                "org.bluez.Device1": {
                    "Address": device.Address,
                    "Name": device.Name,
                    "Paired": device.Paired,
                    "Trusted": device.Trusted,
                    "Connected": device.Connected,
                }
            }
        
        return objects
    
    def add_device(self, mac_address: str, name: str, device_path: str) -> MockDBusDevice:
        """Add a mock device to the manager."""
        device = MockDBusDevice(mac_address=mac_address, name=name)
        self._devices[device_path] = device
        return device
    
    def remove_device(self, device_path: str) -> None:
        """Remove a mock device from the manager."""
        if device_path in self._devices:
            del self._devices[device_path]
    
    def clear_devices(self) -> None:
        """Remove all mock devices."""
        self._devices.clear()


class MockSystemBus:
    """Mock pydbus SystemBus."""
    
    def __init__(self):
        self._adapter = MockDBusAdapter()
        self._object_manager = MockObjectManager()
        self._devices: dict[str, MockDBusDevice] = {}
        self._get_should_fail_for: set[str] = set()
    
    def get(self, bus_name: str, object_path: str) -> Any:
        """Mock get method for D-Bus objects."""
        # Check if this path should fail
        if object_path in self._get_should_fail_for:
            raise Exception(f"Failed to get object: {object_path}")
        
        # Return object manager (check first)
        if object_path == "/":
            return self._object_manager
        
        # Return device (check before adapter since device paths contain adapter path)
        if "/dev_" in object_path:
            if object_path in self._devices:
                return self._devices[object_path]
            else:
                raise Exception(f"Device not found: {object_path}")
        
        # Return adapter
        if object_path.startswith("/org/bluez/hci"):
            return self._adapter
        
        raise Exception(f"Unknown object path: {object_path}")
    
    def add_device(
        self,
        mac_address: str,
        name: str = "Test Device",
        adapter_path: str = "/org/bluez/hci0"
    ) -> MockDBusDevice:
        """Add a mock device."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        device = MockDBusDevice(mac_address=mac_address, name=name)
        self._devices[device_path] = device
        # Also add to object manager for discovery
        self._object_manager.add_device(mac_address, name, device_path)
        return device
    
    def remove_device(self, mac_address: str, adapter_path: str = "/org/bluez/hci0") -> None:
        """Remove a mock device."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        if device_path in self._devices:
            del self._devices[device_path]
        self._object_manager.remove_device(device_path)
    
    def set_get_should_fail(self, object_path: str, should_fail: bool = True) -> None:
        """Configure get() to fail for specific path."""
        if should_fail:
            self._get_should_fail_for.add(object_path)
        else:
            self._get_should_fail_for.discard(object_path)
    
    def clear_all_devices(self) -> None:
        """Remove all mock devices."""
        self._devices.clear()
        self._object_manager.clear_devices()
    
    @property
    def adapter(self) -> MockDBusAdapter:
        """Get the mock adapter."""
        return self._adapter
    
    @property
    def object_manager(self) -> MockObjectManager:
        """Get the mock object manager."""
        return self._object_manager


def create_mock_pydbus_module() -> MagicMock:
    """Create a mock pydbus module for testing.
    
    Returns:
        Mock pydbus module with SystemBus that returns MockSystemBus
    """
    mock_pydbus = MagicMock()
    mock_pydbus.SystemBus = MockSystemBus
    return mock_pydbus
