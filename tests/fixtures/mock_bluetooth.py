"""Mock Bluetooth fixtures for testing.

This module provides mock implementations of dbus-fast and D-Bus objects
for testing Bluetooth functionality without requiring actual hardware.

The fake is layered the way the real system is: :class:`MockBlueZ` stands
in for the **bluetoothd daemon** (one agent registry, shared by every
connection) and :class:`MockMessageBus` stands in for a single D-Bus
connection to it (its own device store, its own exported objects, its own
unique bus name).
"""

import inspect
from typing import Any, NamedTuple
from unittest.mock import MagicMock


class AgentRef(NamedTuple):
    """A registered pairing agent: the connection that owns it and its path.

    BlueZ identifies an agent by exactly this pair -- ``agent->owner`` (the
    sender's unique bus name) plus ``agent->path`` -- and needs both to
    dispatch a method call back to it.
    """

    sender: str
    path: str


class MockBlueZ:
    """The fake's stand-in for the **bluetoothd daemon**.

    BlueZ's agent registry is system-global -- one daemon, one registry,
    shared by every D-Bus connection -- so two managers on two connections
    contend for the same default agent. Keeping that registry on the bus
    instead would let two mock managers each quietly become their own
    default and never contend, which no fix could then be tested against.

    The daemon is an **explicit object, not a process-global singleton**.
    Buses are minted from it with :meth:`new_bus`, so a test that wants two
    contending managers shares one ``MockBlueZ`` and a test that wants
    isolation just lets ``MockMessageBus()`` mint its own. Isolation is the
    default and contention is opt-in, so nothing needs resetting between
    tests and cross-test leakage is impossible rather than merely guarded
    against.

    Models three things the real daemon does (see sections 1-3 of
    ``docs/research/bluez-agent-dispatch.md``, on the
    ``research/bluez-agent-dispatch`` branch):

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
        # (":1.7535", ":1.7536", ...). A monotonic counter mirrors that.
        self._next_unique_id = 7535
        self._buses: dict[str, MockMessageBus] = {}
        # sender -> agent object path. BlueZ allows exactly one agent per
        # D-Bus connection: a second RegisterAgent from the same sender is
        # org.bluez.Error.AlreadyExists.
        self._agents: dict[str, str] = {}
        # Head-first queue of senders. Head == the current default agent.
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
        """Register ``sender``'s one agent, entering the default queue.

        An empty queue means you become the default outright (BlueZ >=
        5.51's ``agent_create()``); otherwise you go on the tail.

        ``capability`` is accepted because ``RegisterAgent`` carries it,
        but nothing here reads it: the fake models agent *dispatch*, not
        the IO-capability negotiation BlueZ uses it for.
        """
        if sender in self._agents:
            raise Exception(
                f"org.bluez.Error.AlreadyExists: Agent already registered for {sender}"
            )
        self._agents[sender] = agent_path
        self._default_queue.append(sender)

    def request_default_agent(self, sender: str, agent_path: str) -> None:
        """Move ``sender`` to the head of the default queue.

        The agent it supersedes is neither notified nor released -- it is
        simply no longer the head (``add_default_agent()``).
        """
        if self._agents.get(sender) != agent_path:
            raise Exception(
                f"org.bluez.Error.DoesNotExist: Agent not registered for {sender}"
            )
        if self._default_queue[:1] == [sender]:
            return  # already the head -- no-op
        if sender in self._default_queue:
            self._default_queue.remove(sender)
        self._default_queue.insert(0, sender)

    def unregister_agent(self, sender: str, agent_path: str) -> None:
        """Drop ``sender``'s agent, promoting the next queue entry.

        BlueZ answers ``org.bluez.Error.DoesNotExist`` both when the
        sender has no agent and when ``agent_path`` isn't the one it
        registered (``unregister_agent()``).
        """
        if self._agents.get(sender) != agent_path:
            raise Exception(
                f"org.bluez.Error.DoesNotExist: Agent not registered for {sender}"
            )
        self._drop_agent(sender)

    def disconnect(self, sender: str) -> None:
        """A bus connection dropping -- same teardown as UnregisterAgent.

        BlueZ watches each agent's connection (``agent_create()`` installs
        ``g_dbus_add_disconnect_watch``) and runs the same
        ``remove_default_agent()`` when it drops.
        """
        self._drop_agent(sender)
        self._buses.pop(sender, None)

    def _drop_agent(self, sender: str) -> None:
        """Forget ``sender``'s agent and leave the queue behind it intact.

        ``remove_default_agent()``: dropping the head promotes the next
        entry, and dropping anyone else is invisible to the default.
        """
        self._agents.pop(sender, None)
        if sender in self._default_queue:
            self._default_queue.remove(sender)

    # -- dispatch ----------------------------------------------------------

    def default_agent(self) -> AgentRef | None:
        """The agent at the head of the default queue, if any."""
        if not self._default_queue:
            return None
        sender = self._default_queue[0]
        return AgentRef(sender, self._agents[sender])

    def resolve_agent(self, sender: str) -> AgentRef | None:
        """BlueZ's dispatch rule: the sender's own agent wins; the default
        agent is only a fallback for a sender that registered none.
        """
        own = self._agents.get(sender)
        if own is not None:
            return AgentRef(sender, own)
        return self.default_agent()

    def default_agent_queue(self) -> list[AgentRef]:
        """The whole queue, head first, for assertions."""
        return [AgentRef(s, self._agents[s]) for s in self._default_queue]

    async def invoke_agent(self, target: AgentRef, method_name: str, *args: Any) -> Any:
        """Call ``method_name`` on the agent ``target`` names, on the bus
        that exported it.
        """
        bus = self._buses.get(target.sender)
        if bus is None:
            raise Exception(
                f"org.freedesktop.DBus.Error.NoReply: {target.sender} is gone"
            )
        return await bus.invoke_exported_method(target.path, method_name, *args)

    async def simulate_caller_less_pairing(
        self, device_path: str, method_name: str = "RequestPinCode", *args: Any
    ) -> Any:
        """Simulate a pairing with **no local ``Pair()`` caller** -- the
        device initiating, or pairing raised as a side effect of
        ``Connect()`` on an unbonded device.

        ``device->bonding`` is NULL on these paths, so BlueZ takes
        ``agent_get(NULL)`` and the **default agent** answers.
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
        pairing), this simulates BlueZ asking a pairing agent for the PIN
        via ``RequestPinCode`` and only succeeds if the returned PIN
        matches the device's configured PIN. Devices added without
        ``requires_pin`` pair immediately (Secure Simple Pairing / Just
        Works never requests a PIN).

        Dispatch is **sender-first**, as in real BlueZ: the agent is
        resolved from the connection this proxy came from, falling back to
        the daemon's default agent only when that sender registered none.
        A caller-less pairing -- which has no sender to attribute -- is
        simulated with :meth:`MockBlueZ.simulate_caller_less_pairing`
        instead.
        """
        if self._should_fail.get("pair"):
            raise Exception("Pairing failed")

        required_pin = self._device_data.get("_requires_pin")
        if required_pin is not None:
            bus = self._calling_bus
            if bus is None:
                raise Exception(
                    "org.bluez.Error.AuthenticationFailed: no pairing agent registered"
                )
            supplied_pin = await bus.dispatch_to_agent(
                "RequestPinCode", self._device_data.get("_device_path")
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
        """Mock AgentManager1.RegisterAgent -- records the call for
        assertion and registers the agent with the daemon under this
        connection's unique name.
        """
        self._record_agent_manager_call("RegisterAgent", (agent_path, capability))
        if self._calling_bus is not None:
            self._calling_bus.register_agent(agent_path, capability)

    async def call_request_default_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.RequestDefaultAgent -- records the call for
        assertion and moves this connection's agent to the head of the
        daemon's default-agent queue.
        """
        self._record_agent_manager_call("RequestDefaultAgent", (agent_path,))
        if self._calling_bus is not None:
            self._calling_bus.request_default_agent(agent_path)

    async def call_unregister_agent(self, agent_path: str) -> None:
        """Mock AgentManager1.UnregisterAgent -- records the call for
        assertion and drops this connection's agent from the daemon,
        promoting the next entry in the default-agent queue.
        """
        self._record_agent_manager_call("UnregisterAgent", (agent_path,))
        if self._calling_bus is not None:
            self._calling_bus.unregister_agent(agent_path)

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
    """Mock dbus-fast async MessageBus -- one D-Bus *connection*.

    Devices, exported objects and recorded AgentManager1 calls are this
    connection's own. The agent registry is not: it belongs to the
    :class:`MockBlueZ` daemon this bus is connected to. A bus constructed
    with no daemon mints a private one, so a lone ``MockMessageBus``
    behaves as if it were the only client on the system.
    """

    def __init__(self, bus_type: Any = None, bluez: "MockBlueZ | None" = None):
        self.bus_type = bus_type
        self._devices: dict[str, dict[str, Any]] = {}
        self._introspection_cache: dict[str, MockNode] = {}
        self._should_fail_paths: set[str] = set()
        self._exported_objects: dict[str, Any] = {}
        self._agent_manager_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.bluez = bluez if bluez is not None else MockBlueZ()
        self.unique_name = self.bluez.attach(self)

    async def connect(self) -> "MockMessageBus":
        """Mock connect method."""
        return self

    def disconnect(self) -> None:
        """Mock dbus-fast MessageBus.disconnect -- drops this connection.

        BlueZ watches each agent's bus connection and runs the same
        teardown as UnregisterAgent when it drops, **promoting** the next
        entry in the default-agent queue. ``BluetoothManager.close()``
        calls this, so the fake needs it to model the handoff.
        """
        self.bluez.disconnect(self.unique_name)

    def get_default_agent(self) -> str | None:
        """The daemon's current default pairing agent path, if any."""
        target = self.bluez.default_agent()
        return target.path if target is not None else None

    def register_agent(self, agent_path: str, capability: str) -> None:
        """Register this connection's pairing agent with the daemon."""
        self.bluez.register_agent(self.unique_name, agent_path, capability)

    def request_default_agent(self, agent_path: str) -> None:
        """Ask the daemon to make this connection's agent the default."""
        self.bluez.request_default_agent(self.unique_name, agent_path)

    def unregister_agent(self, agent_path: str) -> None:
        """Drop this connection's agent from the daemon."""
        self.bluez.unregister_agent(self.unique_name, agent_path)

    async def dispatch_to_agent(self, method_name: str, *args: Any) -> Any:
        """Dispatch an ``Agent1`` call raised by an operation *this*
        connection asked for -- so the agent is resolved sender-first,
        with the default agent as the fallback.
        """
        target = self.bluez.resolve_agent(self.unique_name)
        if target is None:
            raise Exception(
                "org.bluez.Error.AuthenticationFailed: no pairing agent registered"
            )
        return await self.bluez.invoke_agent(target, method_name, *args)

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
