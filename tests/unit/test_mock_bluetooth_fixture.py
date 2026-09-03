"""Unit tests for the mock D-Bus fixture itself.

Covers the fake's ability to export local objects and simulate inbound
BlueZ method calls against them, record AgentManager1 registration
call sequencing, and remove devices via the adapter's RemoveDevice call.
These capabilities have no production caller yet — they exist so later
Bluetooth agent/pairing tickets can be tested (see issue #13's series).
"""

import pytest
from dbus_fast.signature import Variant

from tests.fixtures.mock_bluetooth import (
    MockBlueZ,
    MockMessageBus,
    MockProxyInterface,
    create_mock_message_bus,
)


class TestExportedObjectDispatch:
    """Test exporting a local object at a path and dispatching to it."""

    @pytest.mark.asyncio
    async def test_dispatches_sync_method_on_exported_object(self):
        bus = create_mock_message_bus()

        class FakeAgent:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def Release(self) -> None:
                self.calls.append("Release")

        agent = FakeAgent()
        bus.export("/org/sp_rtk_base_relay/agent", agent)

        await bus.invoke_exported_method("/org/sp_rtk_base_relay/agent", "Release")

        assert agent.calls == ["Release"]

    @pytest.mark.asyncio
    async def test_dispatches_async_method_with_args_and_return_value(self):
        bus = create_mock_message_bus()

        class FakeAgent:
            async def RequestPinCode(self, device_path: str) -> str:
                return f"pin-for-{device_path}"

        bus.export("/org/sp_rtk_base_relay/agent", FakeAgent())

        result = await bus.invoke_exported_method(
            "/org/sp_rtk_base_relay/agent",
            "RequestPinCode",
            "/org/bluez/hci0/dev_AA_BB",
        )

        assert result == "pin-for-/org/bluez/hci0/dev_AA_BB"

    @pytest.mark.asyncio
    async def test_dispatch_fails_when_nothing_exported_at_path(self):
        bus = create_mock_message_bus()

        with pytest.raises(Exception):
            await bus.invoke_exported_method("/not/exported", "Release")

    @pytest.mark.asyncio
    async def test_dispatch_fails_for_unknown_method(self):
        bus = create_mock_message_bus()

        class FakeAgent:
            pass

        bus.export("/org/sp_rtk_base_relay/agent", FakeAgent())

        with pytest.raises(Exception):
            await bus.invoke_exported_method(
                "/org/sp_rtk_base_relay/agent", "NoSuchMethod"
            )

    @pytest.mark.asyncio
    async def test_unexport_removes_object_at_path(self):
        bus = create_mock_message_bus()

        class FakeAgent:
            def Release(self) -> None:
                pass

        bus.export("/org/sp_rtk_base_relay/agent", FakeAgent())
        bus.unexport("/org/sp_rtk_base_relay/agent")

        with pytest.raises(Exception):
            await bus.invoke_exported_method("/org/sp_rtk_base_relay/agent", "Release")

    @pytest.mark.asyncio
    async def test_export_replaces_object_previously_exported_at_same_path(self):
        bus = create_mock_message_bus()

        class FirstAgent:
            def Release(self) -> str:
                return "first"

        class SecondAgent:
            def Release(self) -> str:
                return "second"

        bus.export("/org/sp_rtk_base_relay/agent", FirstAgent())
        bus.export("/org/sp_rtk_base_relay/agent", SecondAgent())

        result = await bus.invoke_exported_method(
            "/org/sp_rtk_base_relay/agent", "Release"
        )

        assert result == "second"


class TestAgentManagerFake:
    """Test the fake org.bluez.AgentManager1 interface at /org/bluez."""

    @pytest.mark.asyncio
    async def test_register_agent_is_recorded(self):
        bus = create_mock_message_bus()
        proxy = bus.get_proxy_object("org.bluez", "/org/bluez", None)
        agent_manager = proxy.get_interface("org.bluez.AgentManager1")

        await agent_manager.call_register_agent(
            "/org/sp_rtk_base_relay/agent", "KeyboardDisplay"
        )

        assert bus.get_agent_manager_calls() == [
            ("RegisterAgent", ("/org/sp_rtk_base_relay/agent", "KeyboardDisplay"))
        ]

    @pytest.mark.asyncio
    async def test_records_register_request_default_and_unregister_in_order(self):
        bus = create_mock_message_bus()
        proxy = bus.get_proxy_object("org.bluez", "/org/bluez", None)
        agent_manager = proxy.get_interface("org.bluez.AgentManager1")
        agent_path = "/org/sp_rtk_base_relay/agent"

        await agent_manager.call_register_agent(agent_path, "KeyboardDisplay")
        await agent_manager.call_request_default_agent(agent_path)
        await agent_manager.call_unregister_agent(agent_path)

        assert bus.get_agent_manager_calls() == [
            ("RegisterAgent", (agent_path, "KeyboardDisplay")),
            ("RequestDefaultAgent", (agent_path,)),
            ("UnregisterAgent", (agent_path,)),
        ]

    @pytest.mark.asyncio
    async def test_agent_manager_calls_are_isolated_per_bus_instance(self):
        bus_a = create_mock_message_bus()
        bus_b = create_mock_message_bus()

        agent_manager_a = bus_a.get_proxy_object(
            "org.bluez", "/org/bluez", None
        ).get_interface("org.bluez.AgentManager1")
        await agent_manager_a.call_register_agent("/agent/a", "KeyboardDisplay")

        assert bus_b.get_agent_manager_calls() == []


class TestAdapterRemoveDevice:
    """Test RemoveDevice on the fake org.bluez.Adapter1 interface."""

    @pytest.mark.asyncio
    async def test_remove_device_deletes_it_from_the_fixtures_device_store(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF", adapter_path="/org/bluez/hci0")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        assert bus.get_device_data("AA:BB:CC:DD:EE:FF") is not None

        adapter_proxy = bus.get_proxy_object("org.bluez", "/org/bluez/hci0", None)
        adapter = adapter_proxy.get_interface("org.bluez.Adapter1")
        await adapter.call_remove_device(device_path)

        assert bus.get_device_data("AA:BB:CC:DD:EE:FF") is None

    @pytest.mark.asyncio
    async def test_device_lookup_fails_the_same_way_as_the_out_of_band_helper(self):
        bus_via_adapter_call = create_mock_message_bus()
        bus_via_helper = create_mock_message_bus()
        mac = "AA:BB:CC:DD:EE:FF"
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        bus_via_adapter_call.add_device(mac)
        adapter = bus_via_adapter_call.get_proxy_object(
            "org.bluez", "/org/bluez/hci0", None
        ).get_interface("org.bluez.Adapter1")
        await adapter.call_remove_device(device_path)

        bus_via_helper.add_device(mac)
        bus_via_helper.remove_device(mac)

        with pytest.raises(Exception, match="DoesNotExist"):
            await bus_via_adapter_call.introspect("org.bluez", device_path)
        with pytest.raises(Exception, match="DoesNotExist"):
            await bus_via_helper.introspect("org.bluez", device_path)

    @pytest.mark.asyncio
    async def test_remove_device_raises_for_unknown_device_path(self):
        bus = create_mock_message_bus()
        adapter = bus.get_proxy_object(
            "org.bluez", "/org/bluez/hci0", None
        ).get_interface("org.bluez.Adapter1")

        with pytest.raises(Exception):
            await adapter.call_remove_device("/org/bluez/hci0/dev_NOT_THERE")


class TestExportedMethodReturnValues:
    """A @dbus_method()-decorated method's real return value must survive
    dispatch through invoke_exported_method.

    Real dbus-fast wraps @dbus_method()-decorated methods so that calling
    the wrapper directly always returns None -- the real message
    dispatcher instead calls the wrapper's stashed "__DBUS_METHOD".fn
    directly (see dbus_fast.message_bus.MessageBus._callback_method_handler).
    invoke_exported_method must mirror that so tests can observe real
    return values (e.g. a pairing agent's RequestPinCode PIN) exactly as
    BlueZ would receive them.
    """

    @pytest.mark.asyncio
    async def test_decorated_method_return_value_is_not_discarded(self):
        from typing import Annotated

        from dbus_fast.annotations import DBusSignature
        from dbus_fast.service import ServiceInterface, dbus_method

        class RealAgent(ServiceInterface):
            def __init__(self) -> None:
                super().__init__("org.bluez.Agent1")

            @dbus_method()
            def RequestPinCode(
                self, device: Annotated[str, DBusSignature("o")]
            ) -> Annotated[str, DBusSignature("s")]:
                return f"pin-for-{device}"

        bus = create_mock_message_bus()
        bus.export("/agent", RealAgent())

        result = await bus.invoke_exported_method(
            "/agent", "RequestPinCode", "/org/bluez/hci0/dev_AA"
        )

        assert result == "pin-for-/org/bluez/hci0/dev_AA"

    @pytest.mark.asyncio
    async def test_decorated_method_exception_still_propagates(self):
        from typing import Annotated

        from dbus_fast import DBusError
        from dbus_fast.annotations import DBusSignature
        from dbus_fast.service import ServiceInterface, dbus_method

        class RealAgent(ServiceInterface):
            def __init__(self) -> None:
                super().__init__("org.bluez.Agent1")

            @dbus_method()
            def RequestPinCode(
                self, device: Annotated[str, DBusSignature("o")]
            ) -> Annotated[str, DBusSignature("s")]:
                raise DBusError("org.bluez.Error.Rejected", "no PIN")

        bus = create_mock_message_bus()
        bus.export("/agent", RealAgent())

        with pytest.raises(DBusError):
            await bus.invoke_exported_method(
                "/agent", "RequestPinCode", "/org/bluez/hci0/dev_AA"
            )


class TestDefaultAgentTracking:
    """The fake tracks which agent is currently the default so call_pair
    can simulate BlueZ dispatching a PIN request to it.
    """

    @pytest.mark.asyncio
    async def test_request_default_agent_records_the_path(self):
        bus = create_mock_message_bus()
        agent_manager = bus.get_proxy_object(
            "org.bluez", "/org/bluez", None
        ).get_interface("org.bluez.AgentManager1")

        await agent_manager.call_register_agent("/agent", "KeyboardOnly")
        await agent_manager.call_request_default_agent("/agent")

        assert bus.get_default_agent() == "/agent"

    @pytest.mark.asyncio
    async def test_unregister_agent_clears_the_default_path(self):
        bus = create_mock_message_bus()
        agent_manager = bus.get_proxy_object(
            "org.bluez", "/org/bluez", None
        ).get_interface("org.bluez.AgentManager1")

        await agent_manager.call_register_agent("/agent", "KeyboardOnly")
        await agent_manager.call_request_default_agent("/agent")
        await agent_manager.call_unregister_agent("/agent")

        assert bus.get_default_agent() is None


class TestPinCodePairingSimulation:
    """call_pair simulates BlueZ asking the registered default agent for
    a PIN when the device was added with requires_pin=...
    """

    @pytest.mark.asyncio
    async def test_pair_succeeds_when_agent_returns_matching_pin(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        class PinAgent:
            def RequestPinCode(self, device: str) -> str:
                assert device == device_path
                return "1234"

        bus.export("/agent", PinAgent())
        agent_manager = bus.get_proxy_object(
            "org.bluez", "/org/bluez", None
        ).get_interface("org.bluez.AgentManager1")
        await agent_manager.call_register_agent("/agent", "KeyboardOnly")
        await agent_manager.call_request_default_agent("/agent")

        device = bus.get_proxy_object("org.bluez", device_path, None).get_interface(
            "org.bluez.Device1"
        )
        await device.call_pair()

        assert bus.get_device_data("AA:BB:CC:DD:EE:FF")["Paired"] is True

    @pytest.mark.asyncio
    async def test_pair_fails_when_agent_returns_wrong_pin(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        class WrongPinAgent:
            def RequestPinCode(self, device: str) -> str:
                return "0000"

        bus.export("/agent", WrongPinAgent())
        agent_manager = bus.get_proxy_object(
            "org.bluez", "/org/bluez", None
        ).get_interface("org.bluez.AgentManager1")
        await agent_manager.call_register_agent("/agent", "KeyboardOnly")
        await agent_manager.call_request_default_agent("/agent")

        device = bus.get_proxy_object("org.bluez", device_path, None).get_interface(
            "org.bluez.Device1"
        )

        with pytest.raises(Exception, match="AuthenticationFailed"):
            await device.call_pair()

        assert bus.get_device_data("AA:BB:CC:DD:EE:FF")["Paired"] is False

    @pytest.mark.asyncio
    async def test_pair_fails_when_no_agent_registered(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        device = bus.get_proxy_object("org.bluez", device_path, None).get_interface(
            "org.bluez.Device1"
        )

        with pytest.raises(Exception, match="AuthenticationFailed"):
            await device.call_pair()

    @pytest.mark.asyncio
    async def test_device_without_requires_pin_pairs_immediately(self):
        """Secure Simple Pairing / Just Works devices are unaffected."""
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        device = bus.get_proxy_object("org.bluez", device_path, None).get_interface(
            "org.bluez.Device1"
        )
        await device.call_pair()

        assert bus.get_device_data("AA:BB:CC:DD:EE:FF")["Paired"] is True


class TestExistingBehaviourUnaffected:
    """Guard rails: unrelated fixture behaviour must be untouched."""

    @pytest.mark.asyncio
    async def test_root_object_manager_still_lists_managed_devices(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF")

        root_proxy = bus.get_proxy_object("org.bluez", "/", None)
        manager = root_proxy.get_interface("org.freedesktop.DBus.ObjectManager")
        objects = await manager.call_get_managed_objects()

        assert "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF" in objects

    @pytest.mark.asyncio
    async def test_device_path_introspection_still_works(self):
        bus = create_mock_message_bus()
        bus.add_device("AA:BB:CC:DD:EE:FF")

        node = await bus.introspect(
            "org.bluez", "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        )

        assert any(i.name == "org.bluez.Device1" for i in node.interfaces)


class _PinAgent:
    """A pairing agent that answers RequestPinCode with a fixed PIN."""

    def __init__(self, pin: str) -> None:
        self.pin = pin

    def RequestPinCode(self, device: str) -> str:
        return self.pin


def _agent_manager(bus: MockMessageBus) -> MockProxyInterface:
    """BlueZ's AgentManager1 interface as reached from ``bus``."""
    return bus.get_proxy_object("org.bluez", "/org/bluez", None).get_interface(
        "org.bluez.AgentManager1"
    )


async def _register_via_proxy(
    bus: MockMessageBus, agent_path: str, make_default: bool = False
) -> None:
    """Register ``agent_path`` from ``bus`` the way a manager does -- through
    the AgentManager1 proxy rather than by calling the daemon directly.
    """
    agent_manager = _agent_manager(bus)
    await agent_manager.call_register_agent(agent_path, "KeyboardOnly")
    if make_default:
        await agent_manager.call_request_default_agent(agent_path)


class TestMockBlueZAgentRegistry:
    """The agent registry is daemon state, keyed by sender.

    BlueZ runs one registry per bluetoothd, shared by every D-Bus
    connection. ``MockBlueZ`` is the fake's stand-in for that daemon, and
    it is an explicit object rather than a process global: buses minted
    from one daemon contend, and a bus made on its own is isolated.
    """

    def test_a_bus_made_on_its_own_gets_a_private_daemon(self):
        bus_a = create_mock_message_bus()
        bus_b = create_mock_message_bus()

        assert bus_a.bluez is not bus_b.bluez

    def test_buses_minted_from_one_daemon_share_its_registry(self):
        bluez = MockBlueZ()

        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        assert bus_a.bluez is bluez
        assert bus_b.bluez is bluez

    def test_daemon_allocates_a_distinct_unique_name_per_bus(self):
        bluez = MockBlueZ()

        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        assert bus_a.unique_name.startswith(":1.")
        assert bus_b.unique_name.startswith(":1.")
        assert bus_a.unique_name != bus_b.unique_name

    def test_agents_are_keyed_by_sender_so_two_buses_both_register(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        assert bluez.resolve_agent(bus_a.unique_name) == (
            bus_a.unique_name,
            "/agent/a",
        )
        assert bluez.resolve_agent(bus_b.unique_name) == (
            bus_b.unique_name,
            "/agent/b",
        )

    def test_a_second_registration_from_the_same_sender_is_already_exists(self):
        """BlueZ allows exactly one agent per D-Bus connection."""
        bluez = MockBlueZ()
        bus = bluez.new_bus()

        bluez.register_agent(bus.unique_name, "/agent", "KeyboardOnly")

        with pytest.raises(Exception, match="AlreadyExists"):
            bluez.register_agent(bus.unique_name, "/other-agent", "KeyboardOnly")

    def test_a_sender_with_no_agent_resolves_to_nothing_when_none_registered(self):
        bluez = MockBlueZ()
        bus = bluez.new_bus()

        assert bluez.resolve_agent(bus.unique_name) is None


class TestDefaultAgentQueue:
    """The default-agent queue is head-first: the head is the default."""

    def test_registering_into_an_empty_queue_makes_you_the_default(self):
        """BlueZ >= 5.51: the first agent to register becomes the default
        without calling RequestDefaultAgent.
        """
        bluez = MockBlueZ()
        bus = bluez.new_bus()

        bluez.register_agent(bus.unique_name, "/agent", "KeyboardOnly")

        assert bluez.default_agent() == (bus.unique_name, "/agent")

    def test_registering_into_a_non_empty_queue_appends_to_the_tail(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        assert bluez.default_agent_queue() == [
            (bus_a.unique_name, "/agent/a"),
            (bus_b.unique_name, "/agent/b"),
        ]

    def test_request_default_agent_moves_the_caller_to_the_head(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        bluez.request_default_agent(bus_b.unique_name, "/agent/b")

        assert bluez.default_agent_queue() == [
            (bus_b.unique_name, "/agent/b"),
            (bus_a.unique_name, "/agent/a"),
        ]

    def test_request_default_agent_from_the_head_is_a_noop(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        bluez.request_default_agent(bus_a.unique_name, "/agent/a")

        assert bluez.default_agent_queue() == [
            (bus_a.unique_name, "/agent/a"),
            (bus_b.unique_name, "/agent/b"),
        ]

    def test_request_default_agent_for_an_unregistered_agent_raises(self):
        bluez = MockBlueZ()
        bus = bluez.new_bus()

        with pytest.raises(Exception, match="DoesNotExist"):
            bluez.request_default_agent(bus.unique_name, "/agent")

    def test_unregistering_the_default_promotes_the_next_agent(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")
        bluez.request_default_agent(bus_b.unique_name, "/agent/b")

        bluez.unregister_agent(bus_b.unique_name, "/agent/b")

        assert bluez.default_agent() == (bus_a.unique_name, "/agent/a")

    def test_unregistering_a_non_default_leaves_the_head_alone(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        bluez.unregister_agent(bus_b.unique_name, "/agent/b")

        assert bluez.default_agent_queue() == [(bus_a.unique_name, "/agent/a")]

    def test_unregistering_an_agent_this_sender_never_had_raises(self):
        """BlueZ answers DoesNotExist for an agent it can't attribute to
        the calling sender, whether or not one is registered.
        """
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")

        with pytest.raises(Exception, match="DoesNotExist"):
            bluez.unregister_agent(bus_b.unique_name, "/agent/a")
        with pytest.raises(Exception, match="DoesNotExist"):
            bluez.unregister_agent(bus_a.unique_name, "/some/other/agent")

        assert bluez.default_agent() == (bus_a.unique_name, "/agent/a")

    def test_a_bus_disconnect_promotes_the_next_agent(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")
        bluez.request_default_agent(bus_b.unique_name, "/agent/b")

        bus_b.disconnect()

        assert bluez.default_agent() == (bus_a.unique_name, "/agent/a")

    def test_the_default_is_cleared_only_when_every_agent_is_gone(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")
        bluez.register_agent(bus_b.unique_name, "/agent/b", "KeyboardOnly")

        bus_a.disconnect()
        bus_b.disconnect()

        assert bluez.default_agent() is None
        assert bluez.default_agent_queue() == []

    def test_get_default_agent_reports_the_daemon_wide_head(self):
        """The default is not per-bus: B sees the agent A registered."""
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")

        assert bus_b.get_default_agent() == "/agent/a"


class TestAgentManagerDrivesTheDaemon:
    """The AgentManager1 proxy calls land on the daemon, not on the bus."""

    @pytest.mark.asyncio
    async def test_register_agent_through_the_proxy_registers_with_the_daemon(self):
        bluez = MockBlueZ()
        bus = bluez.new_bus()

        await _register_via_proxy(bus, "/agent")

        assert bluez.default_agent() == (bus.unique_name, "/agent")

    @pytest.mark.asyncio
    async def test_a_second_manager_on_another_bus_does_not_take_the_default(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        await _register_via_proxy(bus_a, "/agent/a")
        await _register_via_proxy(bus_b, "/agent/b")

        assert bus_b.get_default_agent() == "/agent/a"

    @pytest.mark.asyncio
    async def test_request_default_agent_through_the_proxy_seizes_the_head(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")

        await _register_via_proxy(bus_b, "/agent/b", make_default=True)

        assert bluez.default_agent() == (bus_b.unique_name, "/agent/b")

    @pytest.mark.asyncio
    async def test_unregister_through_the_proxy_promotes_the_other_agent(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()
        bluez.register_agent(bus_a.unique_name, "/agent/a", "KeyboardOnly")

        await _register_via_proxy(bus_b, "/agent/b", make_default=True)
        await _agent_manager(bus_b).call_unregister_agent("/agent/b")

        assert bluez.default_agent() == (bus_a.unique_name, "/agent/a")


class TestSenderFirstPairDispatch:
    """``Pair()`` resolves the agent from its own caller first.

    The default agent answers only for a caller that registered none --
    the inverse of what the fake used to do (#24 §1).
    """

    MAC = "AA:BB:CC:DD:EE:FF"
    DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    @pytest.mark.asyncio
    async def test_pair_uses_the_callers_own_agent_not_the_default(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        # A holds the default and would answer with the wrong PIN.
        bus_a.export("/agent/a", _PinAgent("0000"))
        await _register_via_proxy(bus_a, "/agent/a", make_default=True)
        bus_b.export("/agent/b", _PinAgent("1234"))
        await _register_via_proxy(bus_b, "/agent/b")

        bus_b.add_device(self.MAC, requires_pin="1234")
        device = bus_b.get_proxy_object(
            "org.bluez", self.DEVICE_PATH, None
        ).get_interface("org.bluez.Device1")
        await device.call_pair()

        device_data = bus_b.get_device_data(self.MAC)
        assert device_data is not None and device_data["Paired"] is True
        assert bluez.default_agent() == (bus_a.unique_name, "/agent/a")

    @pytest.mark.asyncio
    async def test_pair_falls_back_to_the_default_for_an_agentless_caller(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        bus_a.export("/agent/a", _PinAgent("1234"))
        await _register_via_proxy(bus_a, "/agent/a", make_default=True)

        bus_b.add_device(self.MAC, requires_pin="1234")
        device = bus_b.get_proxy_object(
            "org.bluez", self.DEVICE_PATH, None
        ).get_interface("org.bluez.Device1")
        await device.call_pair()

        device_data = bus_b.get_device_data(self.MAC)
        assert device_data is not None and device_data["Paired"] is True


class TestCallerLessPairing:
    """A pairing with no local ``Pair()`` caller goes to the default agent.

    Device-initiated pairing, or pairing raised as a side effect of
    ``Connect()`` on an unbonded device: ``device->bonding`` is NULL, so
    BlueZ takes ``agent_get(NULL)`` (#24 §3, §6.1).
    """

    DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    @pytest.mark.asyncio
    async def test_caller_less_pairing_dispatches_to_the_head_of_the_queue(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        for bus, path, pin in (
            (bus_a, "/agent/a", "1111"),
            (bus_b, "/agent/b", "2222"),
        ):
            bus.export(path, _PinAgent(pin))
            bluez.register_agent(bus.unique_name, path, "KeyboardOnly")

        # B seizes the default, so B -- not the caller-less device's
        # nearest bus -- must answer.
        bluez.request_default_agent(bus_b.unique_name, "/agent/b")

        pin = await bluez.simulate_caller_less_pairing(self.DEVICE_PATH)

        assert pin == "2222"

    @pytest.mark.asyncio
    async def test_caller_less_pairing_fails_with_no_default_agent(self):
        bluez = MockBlueZ()
        bluez.new_bus()

        with pytest.raises(Exception, match="AuthenticationFailed"):
            await bluez.simulate_caller_less_pairing(self.DEVICE_PATH)


class TestBusDisconnect:
    """``MockMessageBus.disconnect()`` models the connection dropping."""

    @pytest.mark.asyncio
    async def test_disconnect_tears_the_agent_down_like_unregister_agent(self):
        bluez = MockBlueZ()
        bus = bluez.new_bus()
        await _register_via_proxy(bus, "/agent")

        bus.disconnect()

        assert bluez.default_agent() is None
        assert bluez.resolve_agent(bus.unique_name) is None

    def test_disconnect_is_idempotent(self):
        bluez = MockBlueZ()
        bus = bluez.new_bus()
        bluez.register_agent(bus.unique_name, "/agent", "KeyboardOnly")

        bus.disconnect()
        bus.disconnect()  # must not raise

        assert bluez.default_agent() is None


class TestDeviceStoreStaysPerBus:
    """Only the agent registry is daemon-wide; devices stay per-bus."""

    def test_a_device_added_to_one_bus_is_invisible_on_another(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        bus_a.add_device("AA:BB:CC:DD:EE:FF")

        assert bus_a.get_device_data("AA:BB:CC:DD:EE:FF") is not None
        assert bus_b.get_device_data("AA:BB:CC:DD:EE:FF") is None


class TestPropertiesGetReturnsVariants:
    """The fake's ``Properties.Get`` must return ``Variant``s, as BlueZ does.

    Returning the raw value made a production truthiness bug invisible for
    two releases (issue #39): ``Variant`` defines no ``__bool__``, so every
    ``Variant`` is truthy -- including one wrapping ``False``. Production
    branched on the result of a property read and so always took the
    "already paired" path, meaning ``Device1.Pair()`` was never called.
    """

    @pytest.mark.asyncio
    async def test_get_returns_a_variant_not_a_raw_value(self):
        bus = create_mock_message_bus()
        bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=False)
        props = bus.get_proxy_object(
            "org.bluez", "/org/bluez/hci0/dev_00_11_22_33_44_55", None
        ).get_interface("org.freedesktop.DBus.Properties")

        result = await props.call_get("org.bluez.Device1", "Paired")

        assert isinstance(result, Variant)
        assert result.value is False

    @pytest.mark.asyncio
    async def test_a_variant_wrapping_false_is_truthy(self):
        """The reason every property read must be unwrapped.

        This is a property of ``dbus_fast.signature.Variant`` itself, not of
        the fake. It is asserted here so the next person to add a property
        read sees why a bare ``if`` on one is a bug.
        """
        bus = create_mock_message_bus()
        bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=False)
        props = bus.get_proxy_object(
            "org.bluez", "/org/bluez/hci0/dev_00_11_22_33_44_55", None
        ).get_interface("org.freedesktop.DBus.Properties")

        result = await props.call_get("org.bluez.Device1", "Paired")

        assert bool(result) is True, "a Variant is always truthy"
        assert bool(result.value) is False, "its wrapped value is not"

    @pytest.mark.asyncio
    async def test_variants_carry_the_signature_bluez_uses(self):
        bus = create_mock_message_bus()
        bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=False)
        props = bus.get_proxy_object(
            "org.bluez", "/org/bluez/hci0/dev_00_11_22_33_44_55", None
        ).get_interface("org.freedesktop.DBus.Properties")

        paired = await props.call_get("org.bluez.Device1", "Paired")
        name = await props.call_get("org.bluez.Device1", "Name")

        assert paired.signature == "b"
        assert name.signature == "s"
