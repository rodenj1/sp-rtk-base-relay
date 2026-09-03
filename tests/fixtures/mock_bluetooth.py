"""Mock Bluetooth fixtures for testing.

This module provides mock implementations of dbus-fast and D-Bus objects
for testing Bluetooth functionality without requiring actual hardware.
"""

import inspect
from typing import Any
from unittest.mock import MagicMock


class MockBlueZ:
    """PROTOTYPE (issue #27): the fake's stand-in for the **bluetoothd daemon**.

    BlueZ's agent registry is system-global -- one daemon, one registry,
    shared by every D-Bus connection. The old fake kept it per
    ``MockMessageBus``, so two mock managers each quietly became their own
    default and never contended, which is why the suite could not express
    issue #22 at all.

    Rather than a process-global singleton (which would leak between
    tests), the daemon is an **explicit object**. Buses are minted from it
    with :meth:`new_bus`, so a test that wants two contending managers
    shares one ``MockBlueZ``, and a test that wants isolation just makes
    its own. ``MockMessageBus()`` with no arguments still gets a private
    daemon, so every existing test is unaffected and nothing needs
    resetting in a fixture.

    Models three things the real daemon does (#24 §1, §2):

    * agents are keyed by **sender** (the connection's unique bus name),
      one agent per connection;
    * ``default_agents`` is a **head-first queue**: registering pushes the
      tail (or the head if the queue is empty, BlueZ >= 5.51),
      ``RequestDefaultAgent`` moves you to the head, and unregistering or
      disconnecting **promotes** whoever is next;
    * dispatch is **sender-first**: ``Pair()``'s caller gets its own agent,
      and the default agent answers only for a caller-less pairing.
    """

    def __init__(self) -> None:
        # dbus-fast hands out one stable unique name per bus connection
        # (":1.7535", ":1.7536", ... -- verified against the installed
        # library in #24). A monotonic counter mirrors that faithfully.
        self._next_unique_id = 7535
        self._buses: dict[str, MockMessageBus] = {}
        # sender -> agent object path. BlueZ allows exactly one agent per
        # D-Bus connection: a second RegisterAgent from the same sender is
        # org.bluez.Error.AlreadyExists.
        self._agents: dict[str, str] = {}
        # Head-first stack of senders. Head == the current default agent.
        self._default_queue: list[str] = []

    def new_bus(self, bus_type: Any = None) -> "MockMessageBus":
        """Mint another connection to this same daemon."""
        return MockMessageBus(bus_type, bluez=self)

    def attach(self, bus: "MockMessageBus") -> str:
        """Register ``bus`` as a connection and return its unique name."""
        unique_name = f":1.{self._next_unique_id}"
        self._next_unique_id += 1
        self._buses[unique_name] = bus
        return unique_name

    # -- AgentManager1 -----------------------------------------------------

    def register_agent(self, sender: str, agent_path: str, capability: str) -> None:
        if sender in self._agents:
            raise Exception(
                f"org.bluez.Error.AlreadyExists: Agent already registered for {sender}"
            )
        self._agents[sender] = agent_path
        # agent_create(): empty queue -> you become the default; otherwise
        # you go on the tail. Either way you enter the queue.
        self._default_queue.append(sender)

    def request_default_agent(self, sender: str, agent_path: str) -> None:
        if self._agents.get(sender) != agent_path:
            raise Exception(
                f"org.bluez.Error.DoesNotExist: Agent not registered for {sender}"
            )
        if self._default_queue[:1] == [sender]:
            return  # add_default_agent(): already head, no-op
        if sender in self._default_queue:
            self._default_queue.remove(sender)
        self._default_queue.insert(0, sender)

    def unregister_agent(self, sender: str, agent_path: str) -> None:
        if self._agents.get(sender) != agent_path:
            return  # BlueZ ignores an UnregisterAgent for an unknown agent
        del self._agents[sender]
        # remove_default_agent(): dropping the head promotes the next entry.
        if sender in self._default_queue:
            self._default_queue.remove(sender)

    def disconnect(self, sender: str) -> None:
        """A bus connection dropping -- same teardown as UnregisterAgent."""
        self._agents.pop(sender, None)
        if sender in self._default_queue:
            self._default_queue.remove(sender)
        self._buses.pop(sender, None)

    # -- dispatch ----------------------------------------------------------

    def default_agent(self) -> tuple[str, str] | None:
        """``(sender, agent_path)`` at the head of the default queue."""
        for sender in self._default_queue:
            path = self._agents.get(sender)
            if path is not None:
                return (sender, path)
        return None

    def resolve_agent(self, sender: str) -> tuple[str, str] | None:
        """BlueZ's dispatch rule: the sender's own agent wins; the default
        agent is only a fallback for a sender that registered none (#24 §1).
        """
        own = self._agents.get(sender)
        if own is not None:
            return (sender, own)
        return self.default_agent()

    def default_agent_queue(self) -> list[tuple[str, str]]:
        """The whole queue, head first, for assertions."""
        return [(s, self._agents[s]) for s in self._default_queue if s in self._agents]

    async def invoke_agent(
        self, target: tuple[str, str], method_name: str, *args: Any
    ) -> Any:
        """Call ``method_name`` on the agent object ``target`` names, on the
        bus that exported it.
        """
        sender, agent_path = target
        bus = self._buses.get(sender)
        if bus is None:
            raise Exception(f"org.freedesktop.DBus.Error.NoReply: {sender} is gone")
        return await bus.invoke_exported_method(agent_path, method_name, *args)

    async def simulate_caller_less_pairing(
        self, device_path: str, method_name: str = "RequestPinCode", *args: Any
    ) -> Any:
        """Simulate a pairing with **no local ``Pair()`` caller** -- the
        device initiating, or pairing raised as a side effect of
        ``Connect()`` on an unbonded device (#24 §6.1).

        ``device->bonding`` is NULL on these paths, so BlueZ takes
        ``agent_get(NULL)`` and the **default agent** answers. This is the
        path the surviving half of #22 lives on, and the old fake had no
        way to express it.
        """
        target = self.default_agent()
        if target is None:
            raise Exception(
                "org.bluez.Error.AuthenticationFailed: no default agent registered"
            )
        return await self.invoke_agent(target, method_name, device_path, *args)


class MockProxyInterface:
    """Mock dbus-fast ProxyInterface with call_* methods."""

    def __init__(
        self,
        interface_name: str,
        device_data: dict[str, Any] | None = None,
        calling_bus: "MockMessageBus | None" = None,
    ):
        self.interface_name = interface_name
        self._device_data = device_data or {}
        self._should_fail: dict[str, bool] = {}
        # The connection this proxy was obtained from -- i.e. the D-Bus
        # *sender* of any call made through it. BlueZ resolves the pairing
        # agent from exactly this.
        self._calling_bus = calling_bus

    async def call_start_discovery(self) -> None:
        """Mock StartDiscovery method."""
        if self._should_fail.get("start_discovery"):
            raise Exception("Discovery failed")

    async def call_stop_discovery(self) -> None:
        """Mock StopDiscovery method."""
        pass

    async def call_pair(self) -> None:
        """Mock Pair method.

        If the device was added with ``requires_pin=...`` (legacy PIN
        pairing), this simulates BlueZ asking the currently-registered
        default pairing agent for the PIN via ``RequestPinCode`` --
        mirroring real BlueZ dispatch to ``Agent1`` -- and only succeeds
        if the returned PIN matches the device's configured PIN. Devices
        added without ``requires_pin`` pair immediately, as before
        (Secure Simple Pairing / Just Works never requests a PIN).
        """
        if self._should_fail.get("pair"):
            raise Exception("Pairing failed")

        required_pin = self._device_data.get("_requires_pin")
        if required_pin is not None:
            # PROTOTYPE (#27): sender-first dispatch. The agent is resolved
            # from the sender of this Pair() call, falling back to the
            # default agent only if that sender registered none -- the rule
            # #24 established. The old fake resolved via the *default*
            # agent unconditionally, which is the caller-less rule applied
            # to a call that always has a caller.
            bus = self._calling_bus or self._device_data.get("_bus")
            device_path = self._device_data.get("_device_path")
            target = (
                bus.bluez.resolve_agent(bus.unique_name) if bus is not None else None
            )
            if bus is None or target is None:
                raise Exception(
                    "org.bluez.Error.AuthenticationFailed: no pairing agent registered"
                )
            supplied_pin = await bus.bluez.invoke_agent(
                target, "RequestPinCode", device_path
            )
            if supplied_pin != required_pin:
                raise Exception("org.bluez.Error.AuthenticationFailed: incorrect PIN")

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
        bus = self._device_data.get("_bus")
        if bus is not None:
            bus.bluez.register_agent(bus.unique_name, agent_path, capability)

    async def call_request_default_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.RequestDefaultAgent -- records the call for
        assertion and tracks ``agent_path`` as the bus's default agent so
        ``call_pair`` can simulate BlueZ dispatching to it.
        """
        self._record_agent_manager_call("RequestDefaultAgent", (agent_path,))
        bus = self._device_data.get("_bus")
        if bus is not None:
            bus.bluez.request_default_agent(bus.unique_name, agent_path)

    async def call_unregister_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.UnregisterAgent -- records the call for
        assertion and clears the tracked default agent if it matches.
        """
        self._record_agent_manager_call("UnregisterAgent", (agent_path,))
        bus = self._device_data.get("_bus")
        if bus is not None:
            bus.bluez.unregister_agent(bus.unique_name, agent_path)

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
        self,
        bus_name: str,
        path: str,
        device_data: dict[str, Any] | None = None,
        calling_bus: "MockMessageBus | None" = None,
    ):
        self.bus_name = bus_name
        self.path = path
        self._device_data = device_data or {}
        self._calling_bus = calling_bus
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
                interface_name, self._device_data, calling_bus=self._calling_bus
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

    def __init__(self, bus_type: Any = None, bluez: "MockBlueZ | None" = None):
        self.bus_type = bus_type
        self._devices: dict[str, dict[str, Any]] = {}
        self._introspection_cache: dict[str, MockNode] = {}
        self._should_fail_paths: set[str] = set()
        self._exported_objects: dict[str, Any] = {}
        self._agent_manager_calls: list[tuple[str, tuple[Any, ...]]] = []
        # PROTOTYPE (#27): the agent registry is daemon state, not bus
        # state. A bus with no daemon supplied gets a private one, so a
        # lone MockMessageBus behaves exactly as before; two buses minted
        # from one MockBlueZ contend the way two real managers do.
        self.bluez = bluez if bluez is not None else MockBlueZ()
        self.unique_name = self.bluez.attach(self)

    async def connect(self) -> "MockMessageBus":
        """Mock connect method."""
        return self

    def disconnect(self) -> None:
        """Mock dbus-fast MessageBus.disconnect -- drops this connection.

        BlueZ watches each agent's bus connection and runs the same
        teardown as UnregisterAgent when it drops, **promoting** the next
        entry in the default queue (#24 §2). ``BluetoothManager.close()``
        calls this, so the fake needs it to model the handoff.
        """
        self.bluez.disconnect(self.unique_name)

    def get_default_agent(self) -> str | None:
        """The current default pairing agent's path, if any (daemon-wide)."""
        target = self.bluez.default_agent()
        return target[1] if target is not None else None

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
            return MockProxyObject(bus_name, path, root_device_data, calling_bus=self)

        # For device paths
        if "/dev_" in path:
            device_data = self._devices.get(path, {})
            return MockProxyObject(bus_name, path, device_data, calling_bus=self)

        # For the BlueZ root object (AgentManager1 lives here)
        if path == "/org/bluez":
            agent_manager_device_data: dict[str, Any] = {
                "_agent_manager_calls": self._agent_manager_calls,
                "_bus": self,
            }
            return MockProxyObject(
                bus_name, path, agent_manager_device_data, calling_bus=self
            )

        # For adapter paths, give Adapter1 access to the device store so
        # RemoveDevice can actually remove entries from it.
        adapter_device_data: dict[str, Any] = {"_devices_store": self._devices}
        return MockProxyObject(bus_name, path, adapter_device_data, calling_bus=self)

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
        requires_pin: str | None = None,
    ) -> None:
        """Add a mock device to the bus.

        Args:
            requires_pin: If set, marks this device as needing legacy PIN
                pairing -- ``call_pair`` will simulate BlueZ asking the
                registered default agent for the PIN and only succeed if
                it matches. If ``None`` (default), the device pairs
                immediately, as Secure Simple Pairing / Just Works does.
        """
        device_path = f"{adapter_path}/dev_{mac_address.replace(':', '_')}"
        self._devices[device_path] = {
            "Address": mac_address,
            "Name": name,
            "Paired": paired,
            "Trusted": trusted,
            "Connected": connected,
            "_bus": self,
            "_device_path": device_path,
        }
        if requires_pin is not None:
            self._devices[device_path]["_requires_pin"] = requires_pin

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
        # A real dbus_fast.service.ServiceInterface method decorated with
        # @dbus_method() is wrapped: calling it directly always returns
        # None regardless of what the underlying function returns (real
        # dbus-fast's message dispatcher instead calls the wrapper's
        # stashed "__DBUS_METHOD".fn directly -- see
        # MessageBus._callback_method_handler). Mirror that so tests can
        # observe real return values (e.g. RequestPinCode's PIN) exactly
        # as BlueZ would receive them. Plain test-double methods (no
        # dbus_method decorator) are called as before.
        dbus_method_meta = getattr(method, "__DBUS_METHOD", None)
        if dbus_method_meta is not None:
            result = dbus_method_meta.fn(obj, *args)
        else:
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
