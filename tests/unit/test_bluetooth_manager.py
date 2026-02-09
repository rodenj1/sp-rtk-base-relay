"""Unit tests for Bluetooth device manager.

Tests the BluetoothManager class which wraps BlueZ D-Bus API operations
for device discovery, pairing, trusting, and connection management.

Updated for dbus-fast migration.
"""

from unittest.mock import patch
import pytest

from tests.fixtures.mock_bluetooth import create_mock_dbus_fast, create_mock_message_bus
from src.sp_base_relay.core.bluetooth_manager import BluetoothManager, BluetoothError


class TestBluetoothManagerInit:
    """Test BluetoothManager initialization."""
    
    def test_init_success(self):
        """Test successful initialization with default adapter."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            
            assert manager.adapter_path == "/org/bluez/hci0"
            assert manager._bus is not None
            assert manager._adapter is not None
    
    def test_init_custom_adapter(self):
        """Test initialization with custom adapter name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager(adapter_name="hci1")
            
            assert manager.adapter_path == "/org/bluez/hci1"
    
    def test_init_dbus_fast_not_available(self):
        """Test initialization fails when dbus-fast not available."""
        with patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', False):
            with pytest.raises(BluetoothError) as exc_info:
                BluetoothManager()
            
            assert "dbus-fast library not available" in str(exc_info.value)
    
    def test_init_adapter_not_found(self):
        """Test initialization fails when adapter not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.set_should_fail("/org/bluez/hci0")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            with pytest.raises(BluetoothError) as exc_info:
                BluetoothManager()
            
            error_msg = str(exc_info.value)
            assert "Failed to initialize Bluetooth adapter" in error_msg or \
                   "Failed to introspect" in error_msg


class TestBluetoothManagerDiscovery:
    """Test device discovery methods."""
    
    def test_find_device_by_name_success(self):
        """Test successful device discovery by name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True), \
             patch('asyncio.sleep'):  # Mock async sleep
            
            manager = BluetoothManager()
            mac = manager.find_device_by_name("RTK_BASE_ROD", scan_timeout=1)
            
            assert mac == "98:D3:51:FE:FE:E4"
    
    def test_find_device_by_name_not_found(self):
        """Test device discovery when device not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True), \
             patch('asyncio.sleep'):
            
            manager = BluetoothManager()
            mac = manager.find_device_by_name("NonExistent", scan_timeout=1)
            
            assert mac is None
    
    def test_find_device_by_mac_exists(self):
        """Test checking if device exists by MAC address."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            exists = manager.find_device_by_mac("98:D3:51:FE:FE:E4")
            
            assert exists is True
    
    def test_find_device_by_mac_not_exists(self):
        """Test checking if device exists when it doesn't."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            exists = manager.find_device_by_mac("00:11:22:33:44:55")
            
            assert exists is False


class TestBluetoothManagerPairing:
    """Test device pairing methods."""
    
    def test_pair_device_success(self):
        """Test successful device pairing."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD", paired=False)
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.pair_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Paired"] is True
    
    def test_pair_device_already_paired(self):
        """Test pairing when device already paired."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD", paired=True)
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.pair_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Paired"] is True
    
    def test_trust_device_success(self):
        """Test successfully trusting a device."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.trust_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Trusted"] is True
    
    def test_trust_device_fails(self):
        """Test trusting device when it fails (device doesn't exist)."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        # Don't add device - will cause failure at introspection
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            
            with pytest.raises(BluetoothError) as exc_info:
                manager.trust_device("98:D3:51:FE:FE:E4")
            
            # Device doesn't exist, so introspection fails before trust
            error_msg = str(exc_info.value)
            assert "DoesNotExist" in error_msg or "Trust failed" in error_msg


class TestBluetoothManagerConnection:
    """Test device connection methods."""
    
    def test_connect_device_success(self):
        """Test successful device connection."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.connect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Connected"] is True
    
    def test_connect_device_already_connected(self):
        """Test connecting when device already connected."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD", connected=True)
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.connect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Connected"] is True
    
    def test_disconnect_device_success(self):
        """Test successful device disconnection."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD", connected=True)
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            result = manager.disconnect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            device_data = mock_bus.get_device_data("98:D3:51:FE:FE:E4")
            assert device_data["Connected"] is False


class TestBluetoothManagerHelpers:
    """Test helper methods."""
    
    def test_discover_rfcomm_channel(self):
        """Test RFCOMM channel discovery."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            channel = manager.discover_rfcomm_channel("98:D3:51:FE:FE:E4")
            
            # Currently returns 1 (SPP standard)
            assert channel == 1
    
    def test_ensure_device_ready_with_name(self):
        """Test ensure_device_ready with device name."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True), \
             patch('asyncio.sleep'):
            
            manager = BluetoothManager()
            mac, channel = manager.ensure_device_ready(device_name="RTK_BASE_ROD")
            
            assert mac == "98:D3:51:FE:FE:E4"
            assert channel == 1
    
    def test_ensure_device_ready_device_not_found(self):
        """Test ensure_device_ready when device not found."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda **_kw: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True), \
             patch('asyncio.sleep'):
            
            manager = BluetoothManager()
            
            with pytest.raises(BluetoothError) as exc_info:
                manager.ensure_device_ready(device_name="NonExistent")
            
            assert "Device NonExistent not found" in str(exc_info.value)
    
    def test_ensure_device_ready_no_name_or_mac(self):
        """Test ensure_device_ready with no device name or MAC."""
        bus_type, _, dbus_error = create_mock_dbus_fast()
        mock_bus = create_mock_message_bus()
        
        with patch('src.sp_base_relay.core.bluetooth_manager.BusType', bus_type), \
             patch('src.sp_base_relay.core.bluetooth_manager.AioMessageBus', lambda bus_type: mock_bus), \
             patch('src.sp_base_relay.core.bluetooth_manager.DBusError', dbus_error), \
             patch('src.sp_base_relay.core.bluetooth_manager._dbus_fast_available', True):
            
            manager = BluetoothManager()
            
            with pytest.raises(BluetoothError) as exc_info:
                manager.ensure_device_ready()
            
            assert "Must provide either device_name or mac_address" in str(exc_info.value)
