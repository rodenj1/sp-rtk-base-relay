"""Unit tests for the mock D-Bus fixture itself.

Covers the fake's ability to export local objects and simulate inbound
BlueZ method calls against them, record AgentManager1 registration
call sequencing, and remove devices via the adapter's RemoveDevice call.
These capabilities have no production caller yet — they exist so later
Bluetooth agent/pairing tickets can be tested (see issue #13's series).
"""

import pytest

from tests.fixtures.mock_bluetooth import create_mock_message_bus


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
