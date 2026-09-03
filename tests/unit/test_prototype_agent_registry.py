"""PROTOTYPE (issue #27) -- the two regression tests the redesigned fake
has to be able to express.

Both are expected to **fail on main** and to pass once #25's chosen fix
lands. They are the concrete proof that the system-global agent registry
in ``MockBlueZ`` makes the multi-instance contention testable offline;
they are not merged as-is.

Run:  uv run pytest tests/unit/test_prototype_agent_registry.py -v
"""

from typing import Any
from unittest.mock import patch

import pytest
from dbus_fast import DBusError as RealDBusError

from src.sp_rtk_base_relay.core.bluetooth_manager import (
    _AGENT_OBJECT_PATH,
    BluetoothManager,
)
from tests.fixtures.mock_bluetooth import MockBlueZ, MockMessageBus


def _build_manager(mock_bus: MockMessageBus, **kwargs: Any) -> BluetoothManager:
    """Same helper as test_bluetooth_manager._build_manager -- patches are
    undone once construction returns, so the module's real ``DBusError`` is
    back in effect when the agent is later invoked.
    """
    from tests.fixtures.mock_bluetooth import create_mock_dbus_fast

    bus_type, _, dbus_error = create_mock_dbus_fast()
    with (
        patch("src.sp_rtk_base_relay.core.bluetooth_manager.BusType", bus_type),
        patch(
            "src.sp_rtk_base_relay.core.bluetooth_manager.AioMessageBus",
            lambda bus_type: mock_bus,
        ),
        patch("src.sp_rtk_base_relay.core.bluetooth_manager.DBusError", dbus_error),
        patch(
            "src.sp_rtk_base_relay.core.bluetooth_manager._dbus_fast_available",
            True,
        ),
    ):
        return BluetoothManager(**kwargs)


def _agent_manager_call_names(bus: MockMessageBus) -> list[str]:
    return [name for name, _ in bus.get_agent_manager_calls()]


class TestSecondManagerDoesNotSeizeTheDefault:
    """Regression test 1 -- the default-agent queue.

    Constructing a second ``BluetoothManager`` must not issue
    ``RequestDefaultAgent``, and the first manager must remain at the head
    of BlueZ's default queue.

    Needs the system-global registry (item 1) and queue promotion (item 3).
    Does **not** need the caller-less simulation (item 2).
    """

    def test_second_manager_issues_no_request_default_agent(self) -> None:
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)  # the relay's long-lived manager
        _build_manager(bus_b)  # a throwaway manager for a UI scan

        assert _agent_manager_call_names(bus_a) == ["RegisterAgent"]
        assert _agent_manager_call_names(bus_b) == ["RegisterAgent"]

    def test_first_manager_stays_head_of_the_default_queue(self) -> None:
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)
        _build_manager(bus_b)

        # Both agents are registered and both are in the queue, but A --
        # registered first, when the queue was empty -- is still the default.
        assert bluez.default_agent_queue() == [
            (bus_a.unique_name, _AGENT_OBJECT_PATH),
            (bus_b.unique_name, _AGENT_OBJECT_PATH),
        ]
        assert bluez.default_agent() == (bus_a.unique_name, _AGENT_OBJECT_PATH)

    def test_closing_the_second_manager_leaves_the_first_as_default(self) -> None:
        """Queue promotion: B going away must not clear the default (map
        note 3's retraction, #24 §2).
        """
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)
        manager_b = _build_manager(bus_b)

        manager_b.close()

        assert bluez.default_agent() == (bus_a.unique_name, _AGENT_OBJECT_PATH)


class TestCallerLessPairingIsDiagnosable:
    """Regression test 2 -- the caller-less diagnostic (map note 5).

    A caller-less ``RequestPinCode`` -- device-initiated, or raised by
    ``Connect()`` on an unbonded device (#24 §6.1) -- reaches us as the
    default agent with an empty ``_pending_pins``. It must be rejected with
    a message that names *that* case, not today's generic
    "No PIN recorded for pending pairing attempt on {device}", which in the
    field is indistinguishable from a wrong PIN.

    Needs the caller-less simulation (item 2).
    """

    DEVICE = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    @pytest.mark.asyncio
    async def test_caller_less_pin_request_is_rejected(self) -> None:
        bluez = MockBlueZ()
        bus = bluez.new_bus()
        _build_manager(bus)

        with pytest.raises(RealDBusError):
            await bluez.simulate_caller_less_pairing(self.DEVICE)

    @pytest.mark.asyncio
    async def test_rejection_names_the_caller_less_case(self) -> None:
        bluez = MockBlueZ()
        bus = bluez.new_bus()
        _build_manager(bus)

        with pytest.raises(RealDBusError) as excinfo:
            await bluez.simulate_caller_less_pairing(self.DEVICE)

        message = str(excinfo.value)
        assert "caller-less" in message.lower()
        assert self.DEVICE in message

    @pytest.mark.asyncio
    async def test_wrong_device_mid_pairing_keeps_the_old_message(self) -> None:
        """The two rejections must be distinguishable. With a local pairing
        genuinely in flight, an unrecognised path is the *other* case and
        keeps the original wording.
        """
        bluez = MockBlueZ()
        bus = bluez.new_bus()
        manager = _build_manager(bus)

        manager._pending_pins["/org/bluez/hci0/dev_11_22_33_44_55_66"] = "1234"

        with pytest.raises(RealDBusError) as excinfo:
            await bluez.simulate_caller_less_pairing(self.DEVICE)

        message = str(excinfo.value)
        assert "caller-less" not in message.lower()
        assert "No PIN recorded" in message
