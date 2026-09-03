"""Unit tests for Bluetooth device manager.

Tests the BluetoothManager class which wraps BlueZ D-Bus API operations
for device discovery, pairing, trusting, and connection management.

Updated for dbus-fast migration.
"""

import logging
from typing import Any
from unittest.mock import patch

import pytest
from dbus_fast import DBusError as RealDBusError

from src.sp_rtk_base_relay.core.bluetooth_manager import (
    _AGENT_CAPABILITY,
    _AGENT_OBJECT_PATH,
    BluetoothError,
    BluetoothManager,
)
from tests.fixtures.mock_bluetooth import (
    MockBlueZ,
    MockProxyInterface,
    create_mock_dbus_fast,
    create_mock_message_bus,
)


def _build_manager(
    mock_bus: Any, claim_default_agent: bool = False
) -> BluetoothManager:
    """Construct a BluetoothManager wired to ``mock_bus`` for the duration
    of construction only -- patches are undone once this returns, so the
    module's real ``DBusError`` is back in effect for any later interaction
    with objects (like the pairing agent) exported on ``mock_bus``.
    """
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
        return BluetoothManager(claim_default_agent=claim_default_agent)


class TestBluetoothManagerInit:
    """Test BluetoothManager initialization."""

    def test_init_success(self):
        """Test successful initialization with default adapter."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager()

            assert manager.adapter_path == "/org/bluez/hci0"
            assert manager._bus is not None
            assert manager._adapter is not None

    def test_init_custom_adapter(self):
        """Test initialization with custom adapter name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager(adapter_name="hci1")

            assert manager.adapter_path == "/org/bluez/hci1"

    def test_init_dbus_fast_not_available(self):
        """Test initialization fails when dbus-fast not available."""
        with patch(
            "src.sp_rtk_base_relay.core.bluetooth_manager._dbus_fast_available", False
        ):
            with pytest.raises(BluetoothError) as exc_info:
                BluetoothManager()

            assert "dbus-fast library not available" in str(exc_info.value)

    def test_init_adapter_not_found(self):
        """Test initialization fails when adapter not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.set_should_fail("/org/bluez/hci0")

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
            with pytest.raises(BluetoothError) as exc_info:
                BluetoothManager()

            error_msg = str(exc_info.value)
            assert (
                "Failed to initialize Bluetooth adapter" in error_msg
                or "Failed to introspect" in error_msg
            )


class TestBluetoothManagerDiscovery:
    """Test device discovery methods."""

    def test_find_device_by_name_success(self):
        """Test successful device discovery by name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            patch("asyncio.sleep"),
        ):  # Mock async sleep
            manager = BluetoothManager()
            mac = manager.find_device_by_name("RTK_GPS_BASE", scan_timeout=1)

            assert mac == "00:11:22:33:44:55"

    def test_find_device_by_name_not_found(self):
        """Test device discovery when device not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()
            mac = manager.find_device_by_name("NonExistent", scan_timeout=1)

            assert mac is None

    def test_find_device_by_mac_exists(self):
        """Test checking if device exists by MAC address."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            exists = manager.find_device_by_mac("00:11:22:33:44:55")

            assert exists is True

    def test_find_device_by_mac_not_exists(self):
        """Test checking if device exists when it doesn't."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager()
            exists = manager.find_device_by_mac("00:11:22:33:44:55")

            assert exists is False


class TestBluetoothManagerPairing:
    """Test device pairing methods."""

    def test_pair_device_returns_true_when_it_creates_the_bond(self):
        """``True`` means this call created the bond (issue #48)."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=False)

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
            manager = BluetoothManager()
            result = manager.pair_device("00:11:22:33:44:55")

            assert result is True
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Paired"] is True

    def test_pair_device_returns_false_when_the_bond_already_exists(self):
        """``False`` means "already bonded, nothing done" -- not failure.

        Failure raises; the return value distinguishes a bond this call
        created from one that was already there (issue #48).
        """
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=True)

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
            manager = BluetoothManager()
            result = manager.pair_device("00:11:22:33:44:55")

            assert result is False
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Paired"] is True

    def test_trust_device_success(self):
        """Test successfully trusting a device."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            result = manager.trust_device("00:11:22:33:44:55")

            assert result is True
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Trusted"] is True

    def test_trust_device_fails(self):
        """Test trusting device when it fails (device doesn't exist)."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        # Don't add device - will cause failure at introspection

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
            manager = BluetoothManager()

            with pytest.raises(BluetoothError) as exc_info:
                manager.trust_device("00:11:22:33:44:55")

            # Device doesn't exist, so introspection fails before trust
            error_msg = str(exc_info.value)
            assert "DoesNotExist" in error_msg or "Trust failed" in error_msg


class TestBluetoothManagerConnection:
    """Test device connection methods."""

    def test_connect_device_success(self):
        """Test successful device connection."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            result = manager.connect_device("00:11:22:33:44:55")

            assert result is True
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Connected"] is True

    def test_connect_device_already_connected(self):
        """Test connecting when device already connected."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", connected=True)

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
            manager = BluetoothManager()
            result = manager.connect_device("00:11:22:33:44:55")

            assert result is True
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Connected"] is True

    def test_disconnect_device_success(self):
        """Test successful device disconnection."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", connected=True)

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
            manager = BluetoothManager()
            result = manager.disconnect_device("00:11:22:33:44:55")

            assert result is True
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Connected"] is False

    def test_connect_device_retries_after_not_available_then_succeeds(self):
        """A transient 'NotAvailable' error is retried, not raised."""
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")
        manager = _build_manager(mock_bus)

        attempts = {"count": 0}
        original_call_connect = MockProxyInterface.call_connect

        async def flaky_call_connect(self: Any) -> None:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise RealDBusError(
                    "org.bluez.Error.NotAvailable",
                    "Operation currently not available",
                )
            await original_call_connect(self)

        with patch.object(MockProxyInterface, "call_connect", flaky_call_connect):
            result = manager.connect_device(
                "00:11:22:33:44:55", max_retries=3, retry_delay=0
            )

        assert result is True
        assert attempts["count"] == 2

    def test_connect_device_retries_up_to_max_attempts_then_raises(self):
        """A persistent 'NotAvailable' error is retried up to max_retries
        times, then connect_device() raises.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")
        manager = _build_manager(mock_bus)

        attempts = {"count": 0}

        async def always_not_available(self: Any) -> None:
            attempts["count"] += 1
            raise RealDBusError(
                "org.bluez.Error.NotAvailable", "Operation currently not available"
            )

        with patch.object(MockProxyInterface, "call_connect", always_not_available):
            with pytest.raises(BluetoothError):
                manager.connect_device(
                    "00:11:22:33:44:55", max_retries=2, retry_delay=0
                )

        assert attempts["count"] == 2

    def test_connect_device_non_retryable_dbus_error_fails_immediately(self):
        """A D-Bus error other than 'NotAvailable' isn't retried."""
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")
        manager = _build_manager(mock_bus)

        with patch.object(
            MockProxyInterface,
            "call_connect",
            side_effect=RealDBusError("org.bluez.Error.Failed", "nope"),
        ):
            with pytest.raises(BluetoothError, match="D-Bus connection error"):
                manager.connect_device(
                    "00:11:22:33:44:55", max_retries=3, retry_delay=0
                )


class TestBluetoothManagerHelpers:
    """Test helper methods."""

    def test_discover_rfcomm_channel(self):
        """Test RFCOMM channel discovery."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager()
            channel = manager.discover_rfcomm_channel("00:11:22:33:44:55")

            # Currently returns 1 (SPP standard)
            assert channel == 1

    def test_ensure_device_ready_with_name(self):
        """Test ensure_device_ready with device name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()
            mac, channel = manager.ensure_device_ready(
                pin="0000", device_name="RTK_GPS_BASE"
            )

            assert mac == "00:11:22:33:44:55"
            assert channel == 1

    def test_ensure_device_ready_device_not_found(self):
        """Test ensure_device_ready when device not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

        with (
            patch("src.sp_rtk_base_relay.core.bluetooth_manager.BusType", bus_type),
            patch(
                "src.sp_rtk_base_relay.core.bluetooth_manager.AioMessageBus",
                lambda **_kw: mock_bus,
            ),
            patch("src.sp_rtk_base_relay.core.bluetooth_manager.DBusError", dbus_error),
            patch(
                "src.sp_rtk_base_relay.core.bluetooth_manager._dbus_fast_available",
                True,
            ),
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()

            with pytest.raises(BluetoothError) as exc_info:
                manager.ensure_device_ready(pin="0000", device_name="NonExistent")

            assert "Device NonExistent not found" in str(exc_info.value)

    def test_ensure_device_ready_no_name_or_mac(self):
        """Test ensure_device_ready with no device name or MAC."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager()

            with pytest.raises(BluetoothError) as exc_info:
                manager.ensure_device_ready(pin="0000")

            assert "Must provide either device_name or mac_address" in str(
                exc_info.value
            )

    def test_ensure_device_ready_with_mac(self):
        """Test ensure_device_ready with MAC address (uses _pair_and_trust)."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            mac, channel = manager.ensure_device_ready(
                pin="0000", mac_address="00:11:22:33:44:55"
            )

            assert mac == "00:11:22:33:44:55"
            assert channel == 1
            device_data = mock_bus.get_device_data("00:11:22:33:44:55")
            assert device_data["Paired"] is True
            assert device_data["Trusted"] is True


class TestBluetoothManagerCacheInvalidation:
    """Test introspection cache invalidation."""

    def test_invalidate_device_cache_removes_entry(self):
        """Test that _invalidate_device_cache removes a cached device path."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            device_path = "/org/bluez/hci0/dev_00_11_22_33_44_55"

            # Manually populate the cache
            manager._introspection_cache[device_path] = "fake_node"  # type: ignore[assignment]
            assert device_path in manager._introspection_cache

            # Invalidate
            manager._invalidate_device_cache(device_path)
            assert device_path not in manager._introspection_cache

    def test_invalidate_device_cache_noop_when_not_cached(self):
        """Test that _invalidate_device_cache is safe when path not in cache."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            manager = BluetoothManager()
            # Should not raise
            manager._invalidate_device_cache("/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF")

    def test_pair_device_invalidates_cache_before_introspection(self):
        """Test that pair_device invalidates the device cache before introspecting.

        This is the core fix: if there's a stale cached introspection for a device,
        pair_device should evict it and re-introspect fresh from D-Bus.
        """
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE", paired=False)

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
            manager = BluetoothManager()
            device_path = "/org/bluez/hci0/dev_00_11_22_33_44_55"

            # Inject a stale "bad" cache entry
            manager._introspection_cache[device_path] = "stale_data"  # type: ignore[assignment]

            # pair_device should invalidate and re-introspect
            result = manager.pair_device("00:11:22:33:44:55")

            assert result is True
            # Cache should now contain fresh introspection, not "stale_data"
            assert manager._introspection_cache.get(device_path) != "stale_data"

    def test_trust_device_invalidates_cache_before_introspection(self):
        """Test that trust_device invalidates the device cache before introspecting."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")

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
            manager = BluetoothManager()
            device_path = "/org/bluez/hci0/dev_00_11_22_33_44_55"

            # Inject a stale cache entry
            manager._introspection_cache[device_path] = "stale_data"  # type: ignore[assignment]

            # trust_device should invalidate and re-introspect
            result = manager.trust_device("00:11:22:33:44:55")

            assert result is True
            assert manager._introspection_cache.get(device_path) != "stale_data"


class TestBluetoothManagerRecovery:
    """Test recovery scan and ensure_device_ready retry logic."""

    def test_ensure_device_ready_waits_for_interface_then_succeeds(self):
        """v2.1.3: when the device path appears mid-poll (BlueZ's two-phase
        rediscovery), ensure_device_ready waits through the poll and
        succeeds on the next iteration once Device1 is present."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        # Device NOT added initially — first introspect raises DoesNotExist,
        # forcing the poll loop to keep retrying.

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
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()

            # Patch _async_wait_for_device_interface so the loop body
            # registers the device on its first failure, then re-polls
            # and finds Device1 present.  Without this, the real poll
            # would call mock_bus.introspect forever (mock has no
            # discovery side-effects).
            original_wait = manager._async_wait_for_device_interface

            async def _patched_wait(mac: str, scan_timeout: int) -> None:
                if "00:11:22:33:44:55" not in [
                    d.split("_")[-1] for d in mock_bus._devices
                ]:
                    mock_bus.add_device("00:11:22:33:44:55", "RTK_GPS_BASE")
                await original_wait(mac, scan_timeout)

            manager._async_wait_for_device_interface = _patched_wait  # type: ignore[assignment]

            mac, channel = manager.ensure_device_ready(
                pin="0000", mac_address="00:11:22:33:44:55"
            )

            assert mac == "00:11:22:33:44:55"
            assert channel == 1

    def test_ensure_device_ready_fails_when_interface_never_appears(self):
        """v2.1.3: when the Device1 interface never populates within
        scan_timeout, ensure_device_ready raises a BluetoothError that
        clearly explains the situation (so the operator can extend the
        timeout or check the device is advertising)."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        # Device never added — introspect always raises DoesNotExist

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
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()

            with pytest.raises(BluetoothError) as exc_info:
                manager.ensure_device_ready(
                    pin="0000", mac_address="00:11:22:33:44:55", scan_timeout=2
                )

            msg = str(exc_info.value)
            assert "did not become available" in msg
            assert "00:11:22:33:44:55" in msg
            assert "Device1 interface never appeared" in msg

    def test_recovery_scan_is_non_fatal_on_failure(self):
        """Test that recovery_scan swallows errors gracefully."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()

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
            patch("asyncio.sleep"),
        ):
            manager = BluetoothManager()
            # Force adapter to None so scan fails
            manager._adapter = None

            # Should not raise
            manager._recovery_scan("00:11:22:33:44:55", scan_seconds=1)


class TestBluetoothManagerPairingAgent:
    """Test the default BlueZ pairing agent (org.bluez.Agent1) lifecycle."""

    def test_agent_registered_but_not_made_default_by_default(self):
        """RegisterAgent is called; RequestDefaultAgent is not, since
        ``claim_default_agent`` defaults to False (issue #31) -- and never
        helped anyway, since registering into an empty queue already makes
        the caller the default (BlueZ >= 5.51).
        """
        mock_bus = create_mock_message_bus()

        _build_manager(mock_bus)

        assert mock_bus.get_agent_manager_calls() == [
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
        ]

    def test_agent_registered_and_made_default_when_claiming(self):
        """With claim_default_agent=True, RequestDefaultAgent follows
        RegisterAgent, in that order.
        """
        mock_bus = create_mock_message_bus()

        _build_manager(mock_bus, claim_default_agent=True)

        assert mock_bus.get_agent_manager_calls() == [
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
            ("RequestDefaultAgent", (_AGENT_OBJECT_PATH,)),
        ]

    def test_agent_exported_before_registration(self):
        """The agent object must be exported before any AgentManager1 call.

        A pairing event racing with startup could otherwise be dispatched
        to an object that doesn't exist yet. Checked against a claiming
        manager so both AgentManager1 calls are exercised.
        """
        mock_bus = create_mock_message_bus()
        events: list[tuple[str, tuple[Any, ...]]] = []
        original_export = mock_bus.export

        def spy_export(path: str, interface: Any) -> None:
            events.append(("Export", (path,)))
            original_export(path, interface)

        mock_bus.export = spy_export  # type: ignore[method-assign]

        _build_manager(mock_bus, claim_default_agent=True)
        events.extend(mock_bus.get_agent_manager_calls())

        assert events == [
            ("Export", (_AGENT_OBJECT_PATH,)),
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
            ("RequestDefaultAgent", (_AGENT_OBJECT_PATH,)),
        ]

    def test_agent_exported_before_registration_without_claiming(self):
        """Same export-before-register ordering holds when not claiming
        the default -- just without the RequestDefaultAgent call.
        """
        mock_bus = create_mock_message_bus()
        events: list[tuple[str, tuple[Any, ...]]] = []
        original_export = mock_bus.export

        def spy_export(path: str, interface: Any) -> None:
            events.append(("Export", (path,)))
            original_export(path, interface)

        mock_bus.export = spy_export  # type: ignore[method-assign]

        _build_manager(mock_bus)
        events.extend(mock_bus.get_agent_manager_calls())

        assert events == [
            ("Export", (_AGENT_OBJECT_PATH,)),
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
        ]

    @pytest.mark.asyncio
    async def test_release_and_cancel_are_noops(self):
        mock_bus = create_mock_message_bus()
        _build_manager(mock_bus)

        await mock_bus.invoke_exported_method(_AGENT_OBJECT_PATH, "Release")
        await mock_bus.invoke_exported_method(_AGENT_OBJECT_PATH, "Cancel")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,args",
        [
            ("RequestConfirmation", ("/org/bluez/hci0/dev_AA_BB", 123456)),
            ("RequestAuthorization", ("/org/bluez/hci0/dev_AA_BB",)),
            ("AuthorizeService", ("/org/bluez/hci0/dev_AA_BB", "00001101-0000")),
        ],
    )
    async def test_confirmation_authorization_and_service_auto_accept(
        self, method_name: str, args: tuple[Any, ...]
    ) -> None:
        mock_bus = create_mock_message_bus()
        _build_manager(mock_bus)

        # Must not raise -- an empty reply is BlueZ's success signal.
        await mock_bus.invoke_exported_method(_AGENT_OBJECT_PATH, method_name, *args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name,args",
        [
            ("RequestPinCode", ("/org/bluez/hci0/dev_AA_BB",)),
            ("DisplayPinCode", ("/org/bluez/hci0/dev_AA_BB", "1234")),
            ("RequestPasskey", ("/org/bluez/hci0/dev_AA_BB",)),
            ("DisplayPasskey", ("/org/bluez/hci0/dev_AA_BB", 123456, 4)),
        ],
    )
    async def test_pin_and_passkey_methods_reject(
        self, method_name: str, args: tuple[Any, ...]
    ) -> None:
        mock_bus = create_mock_message_bus()
        _build_manager(mock_bus)

        with pytest.raises(RealDBusError):
            await mock_bus.invoke_exported_method(
                _AGENT_OBJECT_PATH, method_name, *args
            )

    def test_close_unregisters_agent(self):
        mock_bus = create_mock_message_bus()
        manager = _build_manager(mock_bus)

        manager.close()

        assert ("UnregisterAgent", (_AGENT_OBJECT_PATH,)) in (
            mock_bus.get_agent_manager_calls()
        )

    def test_close_swallows_unregister_failure(self):
        """Unregistering is best-effort -- it must never block or fail shutdown."""
        mock_bus = create_mock_message_bus()
        manager = _build_manager(mock_bus)

        with patch.object(
            MockProxyInterface,
            "call_unregister_agent",
            side_effect=Exception("BlueZ rejected UnregisterAgent"),
        ):
            manager.close()  # must not raise

    @pytest.mark.asyncio
    async def test_caller_less_request_pin_code_names_the_case(self):
        """A RequestPinCode with no local pairing attempt in flight is
        rejected with a message naming the caller-less case, distinct
        from a wrong-PIN rejection (issue #31).
        """
        mock_bus = create_mock_message_bus()
        _build_manager(mock_bus, claim_default_agent=True)
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

        with pytest.raises(RealDBusError) as exc_info:
            await mock_bus.bluez.simulate_caller_less_pairing(device_path)

        message = str(exc_info.value)
        assert "caller-less" in message
        assert "pair_device()" in message
        assert "force_repair()" in message

    @pytest.mark.asyncio
    async def test_pending_pairing_for_another_device_keeps_original_wording(self):
        """A local pairing in flight for one device must not make an
        unrelated request for a different, unrecognized device path read
        as caller-less -- the two rejections must stay textually
        distinguishable.
        """
        mock_bus = create_mock_message_bus()
        manager = _build_manager(mock_bus, claim_default_agent=True)
        manager._pending_pins["/org/bluez/hci0/dev_11_11_11_11_11_11"] = "9999"

        with pytest.raises(RealDBusError) as exc_info:
            await mock_bus.invoke_exported_method(
                _AGENT_OBJECT_PATH,
                "RequestPinCode",
                "/org/bluez/hci0/dev_22_22_22_22_22_22",
            )

        message = str(exc_info.value)
        assert "No PIN recorded for pending pairing attempt" in message
        assert "caller-less" not in message


class TestBluetoothManagerDefaultAgentOwnership:
    """A second BluetoothManager no longer seizes the default pairing
    agent from the first unless it explicitly asks to (issue #31).
    """

    def test_second_manager_without_claiming_does_not_disturb_the_default(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)
        _build_manager(bus_b)

        assert bus_a.get_agent_manager_calls() == [
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
        ]
        assert bus_b.get_agent_manager_calls() == [
            ("RegisterAgent", (_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)),
        ]
        assert [ref.sender for ref in bluez.default_agent_queue()] == [
            bus_a.unique_name,
            bus_b.unique_name,
        ]
        assert bluez.default_agent() == (bus_a.unique_name, _AGENT_OBJECT_PATH)

    def test_claiming_manager_moves_itself_to_the_head(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)
        _build_manager(bus_b, claim_default_agent=True)

        assert bluez.default_agent() == (bus_b.unique_name, _AGENT_OBJECT_PATH)

    def test_closing_the_claiming_manager_promotes_the_first(self):
        bluez = MockBlueZ()
        bus_a = bluez.new_bus()
        bus_b = bluez.new_bus()

        _build_manager(bus_a)
        manager_b = _build_manager(bus_b, claim_default_agent=True)
        assert bluez.default_agent() == (bus_b.unique_name, _AGENT_OBJECT_PATH)

        manager_b.close()

        assert bluez.default_agent() == (bus_a.unique_name, _AGENT_OBJECT_PATH)


class TestBluetoothManagerPinThreading:
    """Test threading the configured PIN through pairing (issue #16)."""

    def test_request_pin_code_returns_recorded_pin_during_pairing(self):
        """RequestPinCode answers with the PIN recorded for the device
        path currently mid-pairing-attempt.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        manager = _build_manager(mock_bus)

        result = manager.pair_device("AA:BB:CC:DD:EE:FF", pin="1234")

        assert result is True
        assert mock_bus.get_device_data("AA:BB:CC:DD:EE:FF")["Paired"] is True

    def test_request_pin_code_rejects_wrong_pin(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        manager = _build_manager(mock_bus)

        with pytest.raises(BluetoothError):
            manager.pair_device("AA:BB:CC:DD:EE:FF", pin="0000")

        assert mock_bus.get_device_data("AA:BB:CC:DD:EE:FF")["Paired"] is False

    def test_pending_pin_is_recorded_before_pairing(self):
        """The PIN is recorded against the device path before Pair() is
        invoked -- verified by an agent that inspects manager state
        mid-call rather than relying on the mock's own PIN check.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        manager = _build_manager(mock_bus)

        recorded_during_call: dict[str, str] = {}
        original_call_pair = MockProxyInterface.call_pair

        async def spy_call_pair(self: Any) -> None:
            recorded_during_call.update(manager._pending_pins)
            await original_call_pair(self)

        with patch.object(MockProxyInterface, "call_pair", spy_call_pair):
            manager.pair_device("AA:BB:CC:DD:EE:FF", pin="5678")

        assert recorded_during_call == {device_path: "5678"}

    def test_pending_pin_is_cleared_after_successful_pairing(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        manager = _build_manager(mock_bus)

        manager.pair_device("AA:BB:CC:DD:EE:FF", pin="5678")

        assert device_path not in manager._pending_pins

    def test_pending_pin_is_cleared_after_failed_pairing(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF")
        device_path = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
        manager = _build_manager(mock_bus)

        with patch.object(
            MockProxyInterface, "call_pair", side_effect=Exception("boom")
        ):
            with pytest.raises(BluetoothError):
                manager.pair_device("AA:BB:CC:DD:EE:FF", pin="5678")

        assert device_path not in manager._pending_pins

    def test_pin_recorded_for_one_device_does_not_leak_to_another(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF", requires_pin="1234")
        mock_bus.add_device("11:22:33:44:55:66", requires_pin="9999")
        manager = _build_manager(mock_bus)

        assert manager.pair_device("AA:BB:CC:DD:EE:FF", pin="1234") is True
        with pytest.raises(BluetoothError):
            # Wrong PIN for this device, even though it's the PIN that
            # would have paired the other device.
            manager.pair_device("11:22:33:44:55:66", pin="1234")

    def test_ensure_device_ready_pairs_cold_device_requiring_legacy_pin(self):
        """End-to-end: a simulated cold/unbonded device that requires
        legacy PIN pairing pairs successfully using the configured PIN.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF", "RTK_GPS_BASE", requires_pin="1234")
        manager = _build_manager(mock_bus)

        mac, channel = manager.ensure_device_ready(
            pin="1234", mac_address="AA:BB:CC:DD:EE:FF"
        )

        assert mac == "AA:BB:CC:DD:EE:FF"
        assert channel == 1
        device_data = mock_bus.get_device_data("AA:BB:CC:DD:EE:FF")
        assert device_data["Paired"] is True
        assert device_data["Trusted"] is True

    def test_ensure_device_ready_fails_with_wrong_configured_pin(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("AA:BB:CC:DD:EE:FF", "RTK_GPS_BASE", requires_pin="1234")
        manager = _build_manager(mock_bus)

        with pytest.raises(BluetoothError):
            manager.ensure_device_ready(pin="0000", mac_address="AA:BB:CC:DD:EE:FF")


class TestBluetoothManagerConnectDevicePin:
    """Test the ephemeral ``pin`` argument on connect_device() (issue #31)."""

    MAC = "AA:BB:CC:DD:EE:FF"
    DEVICE_PATH = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"

    def test_connect_device_with_pin_requires_claiming_manager(self):
        """A caller-less PIN request is always routed to the default
        agent, so a PIN recorded on a non-claiming manager could never be
        reached -- fail fast at the API boundary instead.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC)
        manager = _build_manager(mock_bus)

        with patch.object(
            MockProxyInterface,
            "call_connect",
            side_effect=AssertionError("must not be called"),
        ):
            with pytest.raises(BluetoothError):
                manager.connect_device(self.MAC, pin="1234")

    def test_connect_device_pin_is_recorded_before_connect_and_cleared_after(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC)
        manager = _build_manager(mock_bus, claim_default_agent=True)

        recorded_during_call: dict[str, str] = {}
        original_call_connect = MockProxyInterface.call_connect

        async def spy_call_connect(self: Any) -> None:
            recorded_during_call.update(manager._pending_pins)
            await original_call_connect(self)

        with patch.object(MockProxyInterface, "call_connect", spy_call_connect):
            result = manager.connect_device(self.MAC, pin="4321")

        assert result is True
        assert recorded_during_call == {self.DEVICE_PATH: "4321"}
        assert self.DEVICE_PATH not in manager._pending_pins

    def test_connect_device_pin_is_cleared_after_failed_connection(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC)
        manager = _build_manager(mock_bus, claim_default_agent=True)

        with patch.object(
            MockProxyInterface, "call_connect", side_effect=Exception("boom")
        ):
            with pytest.raises(BluetoothError):
                manager.connect_device(self.MAC, max_retries=1, pin="4321")

        assert self.DEVICE_PATH not in manager._pending_pins


class TestBluetoothManagerForceRepair:
    """Test force_repair() for the same-MAC, PIN-changed case (issue #17)."""

    MAC = "AA:BB:CC:DD:EE:FF"

    def _patch_wait_to_rediscover(
        self, manager: BluetoothManager, mock_bus: Any, requires_pin: str | None
    ) -> None:
        """Simulate BlueZ repopulating org.bluez.Device1 after removal.

        Removing a bond can transiently strip the device's D-Bus
        interface -- the same condition ensure_device_ready already
        polls for. The mock fixture has no automatic rediscovery, so
        this re-adds the device (as force_repair's own polling would
        observe BlueZ doing) right before the real wait loop runs its
        first check.
        """
        original_wait = manager._async_wait_for_device_interface

        async def _patched_wait(mac: str, scan_timeout: int) -> None:
            if mac not in [d.get("Address") for d in mock_bus._devices.values()]:
                mock_bus.add_device(mac, requires_pin=requires_pin)
            await original_wait(mac, scan_timeout)

        manager._async_wait_for_device_interface = _patched_wait  # type: ignore[assignment]

    def test_force_repair_succeeds_end_to_end_with_new_pin(self):
        """A device that starts bonded is re-paired successfully using a
        PIN different from whatever it was previously bonded with.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, paired=True, trusted=True)
        manager = _build_manager(mock_bus)
        self._patch_wait_to_rediscover(manager, mock_bus, requires_pin="9999")

        result = manager.force_repair(self.MAC, pin="9999")

        assert result is True
        device_data = mock_bus.get_device_data(self.MAC)
        assert device_data["Paired"] is True
        assert device_data["Trusted"] is True

    def test_force_repair_completes_without_error_when_not_bonded(self):
        """A "not found" outcome from removal is a harmless no-op."""
        mock_bus = create_mock_message_bus()
        # Device not added at all -- nothing to remove.
        manager = _build_manager(mock_bus)
        self._patch_wait_to_rediscover(manager, mock_bus, requires_pin=None)

        result = manager.force_repair(self.MAC, pin="1234")

        assert result is True
        device_data = mock_bus.get_device_data(self.MAC)
        assert device_data["Paired"] is True
        assert device_data["Trusted"] is True

    def test_force_repair_identifies_remove_stage_on_removal_failure(self):
        """A genuine (non-"not found") removal failure identifies removal
        as the failed stage.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, paired=True, trusted=True)
        manager = _build_manager(mock_bus)

        with patch.object(
            MockProxyInterface,
            "call_remove_device",
            side_effect=Exception("adapter busy"),
        ):
            with pytest.raises(BluetoothError) as exc_info:
                manager.force_repair(self.MAC, pin="1234")

        assert "remove stage failed" in str(exc_info.value)
        # Still bonded -- the caller can tell a retry is free.
        device_data = mock_bus.get_device_data(self.MAC)
        assert device_data["Paired"] is True

    def test_force_repair_identifies_pair_stage_on_pairing_failure(self):
        """Removal succeeds, but pairing then fails -- the raised error
        identifies pairing as the failed stage, and the device is left
        unbonded rather than restored to its prior bond.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, paired=True, trusted=True)
        manager = _build_manager(mock_bus)
        self._patch_wait_to_rediscover(manager, mock_bus, requires_pin=None)

        with patch.object(
            MockProxyInterface, "call_pair", side_effect=Exception("pairing exploded")
        ):
            with pytest.raises(BluetoothError) as exc_info:
                manager.force_repair(self.MAC, pin="1234")

        assert "pair stage failed" in str(exc_info.value)
        # No rollback: the old bond was already removed and was not
        # restored.
        device_data = mock_bus.get_device_data(self.MAC)
        assert device_data is not None
        assert device_data["Paired"] is False

    def test_force_repair_identifies_trust_stage_on_trust_failure(self):
        """Removal and pairing succeed, but trust then fails -- the raised
        error identifies trust as the failed stage.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, paired=True, trusted=True)
        manager = _build_manager(mock_bus)
        self._patch_wait_to_rediscover(manager, mock_bus, requires_pin=None)

        with patch.object(
            MockProxyInterface, "call_set", side_effect=Exception("trust exploded")
        ):
            with pytest.raises(BluetoothError) as exc_info:
                manager.force_repair(self.MAC, pin="1234")

        assert "trust stage failed" in str(exc_info.value)
        device_data = mock_bus.get_device_data(self.MAC)
        assert device_data["Paired"] is True
        assert device_data["Trusted"] is False

    def test_force_repair_requires_pin_argument(self):
        """Omitting pin is a call-site error, not a fallback to a default."""
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, paired=True)
        manager = _build_manager(mock_bus)

        with pytest.raises(TypeError):
            manager.force_repair(self.MAC)  # type: ignore[call-arg]


class TestPairDeviceReturnContract:
    """``pair_device()``'s return value distinguishes two successes.

    ``True`` -- this call created the bond. ``False`` -- the bond was
    already there and nothing was done. Failure raises. Before issue #48
    the value was vestigial (``True`` or raise), so both composers carried
    a dead ``if not pair_device(): raise`` branch that would fire on the
    idempotent success path once ``False`` became reachable.
    """

    MAC = "00:11:22:33:44:55"

    def test_ensure_device_ready_succeeds_when_the_bond_already_exists(self):
        """The idempotent path is a success, not a failure.

        ``ensure_device_ready()`` runs on every relay start, so an
        already-bonded device must not raise.
        """
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=True)
        manager = _build_manager(mock_bus)

        mac, channel = manager.ensure_device_ready(pin="1234", mac_address=self.MAC)

        assert mac == self.MAC
        assert channel == 1
        assert mock_bus.get_device_data(self.MAC)["Trusted"] is True

    def test_ensure_device_ready_bonds_a_cold_device(self):
        """The other success: no bond yet, so this call creates one."""
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=False)
        manager = _build_manager(mock_bus)

        mac, _ = manager.ensure_device_ready(pin="1234", mac_address=self.MAC)

        assert mac == self.MAC
        assert mock_bus.get_device_data(self.MAC)["Paired"] is True


class TestForceRepairRejectsAnIneffectiveRemoval:
    """Force-repair must not report success when its removal did not take.

    ``force_repair()`` discards the bond and re-pairs. If ``pair_device()``
    then answers ``False`` -- "already bonded, nothing done" -- the bond it
    just removed is still there, so the operation silently did nothing.
    This is the assertion that would have caught issue #39 inside
    ``force_repair()`` rather than requiring a field probe.
    """

    MAC = "00:11:22:33:44:55"

    def test_force_repair_raises_when_the_bond_survives_removal(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=True)
        mock_bus.set_device_fault("removal_ineffective", self.MAC)
        manager = _build_manager(mock_bus)

        with pytest.raises(BluetoothError) as exc_info:
            manager.force_repair(self.MAC, pin="1234")

        message = str(exc_info.value)
        assert "pair stage failed" in message
        assert "still bonded" in message


class TestPairingTripwire:
    """A successful Pair() that leaves no bond is logged, not swallowed.

    BlueZ does not do this -- a successful ``Pair()`` reply asserts the
    device was set paired -- so this cross-checks the relay's own
    bookkeeping rather than hedging against BlueZ. It exists because
    issue #39's whole cost was a false success travelling two steps
    before surfacing as a confusing RFCOMM error.
    """

    MAC = "00:11:22:33:44:55"

    def test_disagreement_is_logged_distinctly_and_not_as_a_wrong_pin(self, caplog):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=False)
        mock_bus.set_device_fault("pairing_ineffective", self.MAC)
        manager = _build_manager(mock_bus)

        with caplog.at_level(logging.WARNING):
            result = manager.pair_device(self.MAC, pin="1234")

        assert result is True, "BlueZ reported success, so this is not a failure"
        assert "did not create a bond" in caplog.text
        assert "not a wrong-PIN failure" in caplog.text


class TestPairingIsBounded:
    """A Pair() that never answers must not hang the relay indefinitely.

    BlueZ can return from ``device_bonding_complete()`` without replying
    at all, and ``dbus-fast`` imposes no timeout on its calls, so the
    bound has to come from here.
    """

    MAC = "00:11:22:33:44:55"

    def test_a_pair_call_that_never_answers_times_out(self):
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=False)
        mock_bus.set_device_fault("pairing_hangs", self.MAC)
        manager = _build_manager(mock_bus)

        with (
            patch("src.sp_rtk_base_relay.core.bluetooth_manager._PAIRING_TIMEOUT", 0.2),
            pytest.raises(BluetoothError) as exc_info,
        ):
            manager.pair_device(self.MAC, pin="1234")

        assert "timed out" in str(exc_info.value).lower()

    def test_a_timed_out_pairing_does_not_retain_the_pin(self):
        """The PIN map must be cleaned even when the call is cancelled."""
        mock_bus = create_mock_message_bus()
        mock_bus.add_device(self.MAC, "RTK_GPS_BASE", paired=False)
        mock_bus.set_device_fault("pairing_hangs", self.MAC)
        manager = _build_manager(mock_bus)

        with (
            patch("src.sp_rtk_base_relay.core.bluetooth_manager._PAIRING_TIMEOUT", 0.2),
            pytest.raises(BluetoothError),
        ):
            manager.pair_device(self.MAC, pin="1234")

        assert manager._pending_pins == {}
