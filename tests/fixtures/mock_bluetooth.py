"""Mock Bluetooth fixtures for testing.

This module provides mock implementations of dbus-fast and D-Bus objects
for testing Bluetooth functionality without requiring actual hardware.
"""

import inspect
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

    async def call_set(self, interface: str, property_name: str, value: Any) -> None:
        """Mock Properties Set method.

        Handles both dbus-fast Variant objects and raw tuples.
        """
        if interface == "org.bluez.Device1":
            # Handle dbus-fast Variant objects (have .value attribute)
            if hasattr(value, "value"):
                actual_value = value.value
            elif isinstance(value, tuple) and len(value) == 2:
                _, actual_value = value
            else:
                actual_value = value
            self._device_data[property_name] = actual_value

    async def call_get_managed_objects(self) -> dict[str, dict[str, Any]]:
        """Mock ObjectManager GetManagedObjects method."""
        # This will be populated by the MockMessageBus
        return self._device_data.get("_managed_objects", {})

    def set_should_fail(self, method: str, should_fail: bool = True) -> None:
        """Configure a method to fail for testing."""
        self._should_fail[method] = should_fail

    async def call_register_agent(self, agent_path: str, capability: str) -> None:
        """Mock AgentManager1.RegisterAgent -- records the call for assertion."""
        self._record_agent_manager_call("RegisterAgent", (agent_path, capability))

    async def call_request_default_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.RequestDefaultAgent -- records the call for assertion."""
        self._record_agent_manager_call("RequestDefaultAgent", (agent_path,))

    async def call_unregister_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.UnregisterAgent -- records the call for assertion."""
        self._record_agent_manager_call("UnregisterAgent", (agent_path,))

    def _record_agent_manager_call(self, name: str, args: tuple[Any, ...]) -> None:
        calls = self._device_data.get("_agent_manager_calls")
        if calls is None:
            raise Exception(
                f"{name} called on an interface that is not org.bluez.AgentManager1"
            )
        calls.append((name, args))

    async def call_remove_device(self, device_path: str) -> None:
        """Mock Adapter1.RemoveDevice.

        Actually removes the device from the fixture's internal device
        store (shared with ``MockMessageBus``), so a subsequent lookup of
        ``device_path`` fails exactly as it does after
        ``MockMessageBus.remove_device()`` runs.
        """
        devices_store = self._device_data.get("_devices_store")
        if devices_store is None:
            raise Exception(
                "RemoveDevice called on an interface that is not org.bluez.Adapter1"
            )
        if device_path not in devices_store:
            raise Exception(
                f"org.bluez.Error.DoesNotExist: {device_path} does not exist"
            )
        del devices_store[device_path]


class MockInterface:
    """Mock introspection Interface object."""

    def __init__(self, name: str):
        self.name = name


class MockIntrospection:
    """Mock introspection object compatible with dbus-fast."""

    def __init__(self, interfaces: list[MockInterface]):
        self.interfaces = interfaces


class MockProxyObject:
    """Mock dbus-fast ProxyObject."""

    def __init__(
        self, bus_name: str, path: str, device_data: dict[str, Any] | None = None
    ):
        self.bus_name = bus_name
        self.path = path
        self._device_data = device_data or {}
        self._interfaces: dict[str, MockProxyInterface] = {}

        # Create introspection based on path
        if "/dev_" in path:
            interface_list = [
                MockInterface("org.bluez.Device1"),
                MockInterface("org.freedesktop.DBus.Properties"),
            ]
        elif path == "/":
            interface_list = [
                MockInterface("org.freedesktop.DBus.ObjectManager"),
            ]
        elif path == "/org/bluez":
            interface_list = [
                MockInterface("org.bluez.AgentManager1"),
            ]
        else:
            # Adapter path
            interface_list = [
                MockInterface("org.bluez.Adapter1"),
                MockInterface("org.freedesktop.DBus.Properties"),
            ]

        self.introspection = MockIntrospection(interface_list)

    def get_interface(self, interface_name: str) -> MockProxyInterface:
        """Get a mock interface."""
        if interface_name not in self._interfaces:
            self._interfaces[interface_name] = MockProxyInterface(
                interface_name, self._device_data
            )
        return self._interfaces[interface_name]


class MockNode:
    """Mock introspection Node object.

    Interface list is supplied by the caller so different paths can
    return different interfaces (matching real BlueZ behaviour where
    a stale device path may exist without ``org.bluez.Device1``).
    """

    def __init__(self, path: str, interfaces: list[MockInterface] | None = None):
        self.path = path
        if interfaces is not None:
            self.interfaces = interfaces
        else:
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
        self._exported_objects: dict[str, Any] = {}
        self._agent_manager_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def connect(self) -> "MockMessageBus":
        """Mock connect method."""
        return self

    async def introspect(self, bus_name: str, path: str) -> "MockNode":
        """Mock introspect — returns a MockNode with the interfaces a
        real BlueZ ``bus.introspect()`` call would expose for the
        given path.  Raises DoesNotExist for unregistered device paths
        (mirrors BlueZ behaviour when the device isn't currently
        known to the daemon).
        """
        if path in self._should_fail_paths:
            raise Exception(f"Introspection failed for {path}")

        if "/dev_" in path:
            if path not in self._devices:
                raise Exception(f"org.bluez.Error.DoesNotExist: {path} does not exist")
            return MockNode(
                path,
                interfaces=[
                    MockInterface("org.bluez.Device1"),
                    MockInterface("org.freedesktop.DBus.Properties"),
                ],
            )
        elif path == "/":
            return MockNode(
                path,
                interfaces=[MockInterface("org.freedesktop.DBus.ObjectManager")],
            )
        elif path == "/org/bluez":
            return MockNode(
                path,
                interfaces=[MockInterface("org.bluez.AgentManager1")],
            )
        else:
            return MockNode(
                path,
                interfaces=[
                    MockInterface("org.bluez.Adapter1"),
                    MockInterface("org.freedesktop.DBus.Properties"),
                ],
            )

    def get_proxy_object(
        self, bus_name: str, path: str, introspection: Any
    ) -> MockProxyObject:
        """Get a mock proxy object."""
        if path in self._should_fail_paths:
            raise Exception(f"Failed to get proxy for {path}")

        # For ObjectManager (root path), include managed objects
        if path == "/":
            root_device_data: dict[str, Any] = {
                "_managed_objects": self._get_managed_objects()
            }
            return MockProxyObject(bus_name, path, root_device_data)

        # For device paths
        if "/dev_" in path:
            device_data = self._devices.get(path, {})
            return MockProxyObject(bus_name, path, device_data)

        # For the BlueZ root object (AgentManager1 lives here)
        if path == "/org/bluez":
            agent_manager_device_data: dict[str, Any] = {
                "_agent_manager_calls": self._agent_manager_calls
            }
            return MockProxyObject(bus_name, path, agent_manager_device_data)

        # For adapter paths, give Adapter1 access to the device store so
        # RemoveDevice can actually remove entries from it.
        adapter_device_data: dict[str, Any] = {"_devices_store": self._devices}
        return MockProxyObject(bus_name, path, adapter_device_data)

    def _get_managed_objects(self) -> dict[str, dict[str, Any]]:
        """Get all managed objects for ObjectManager."""
        objects: dict[str, dict[str, Any]] = {}
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
        connected: bool = False,
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

    def remove_device(
        self, mac_address: str, adapter_path: str = "/org/bluez/hci0"
    ) -> None:
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

    def get_device_data(
        self, mac_address: str, adapter_path: str = "/org/bluez/hci0"
    ) -> dict[str, Any] | None:
        """Get device data for inspection in tests."""
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        return self._devices.get(device_path)

    def clear_all_devices(self) -> None:
        """Remove all mock devices."""
        self._devices.clear()

    def export(self, path: str, interface: Any) -> None:
        """Mock dbus-fast MessageBus.export -- register a local object at a
        path (e.g. a pairing agent), so tests can later simulate BlueZ
        dispatching a method call to it via ``invoke_exported_method``.
        """
        self._exported_objects[path] = interface

    def unexport(self, path: str, interface: Any | None = None) -> None:
        """Mock dbus-fast MessageBus.unexport -- remove whatever is
        exported at ``path``.
        """
        self._exported_objects.pop(path, None)

    async def invoke_exported_method(
        self, path: str, method_name: str, *args: Any
    ) -> Any:
        """Simulate BlueZ invoking ``method_name`` on whatever object is
        currently exported at ``path`` (e.g. a registered pairing agent).

        Supports both sync and async methods, mirroring how a real
        ``dbus_fast.service.ServiceInterface`` method may be defined.
        """
        if path not in self._exported_objects:
            raise Exception(
                f"org.freedesktop.DBus.Error.UnknownObject: {path} is not exported"
            )
        obj = self._exported_objects[path]
        method = getattr(obj, method_name, None)
        if method is None:
            raise Exception(
                f"org.freedesktop.DBus.Error.UnknownMethod: {method_name} not found "
                f"on object exported at {path}"
            )
        result = method(*args)
        if inspect.isawaitable(result):
            result = await result
        return result

    def get_agent_manager_calls(self) -> list[tuple[str, tuple[Any, ...]]]:
        """Inspect AgentManager1 registration-related calls (RegisterAgent,
        RequestDefaultAgent, UnregisterAgent) in the order they occurred.
        """
        return list(self._agent_manager_calls)


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
