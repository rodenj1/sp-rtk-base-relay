"""Unit tests for Bluetooth device manager.

Tests the BluetoothManager class which wraps BlueZ D-Bus API operations
for device discovery, pairing, trusting, and connection management.
"""

import sys
from unittest.mock import patch, MagicMock
import pytest

from tests.fixtures.mock_bluetooth import create_mock_pydbus_module, MockSystemBus
from src.sp_base_relay.core.bluetooth_manager import BluetoothManager, BluetoothError


class TestBluetoothManagerInit:
    """Test BluetoothManager initialization."""
    
    def test_init_success(self):
        """Test successful initialization with default adapter."""
        mock_pydbus = create_mock_pydbus_module()
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            # Force reload to use mocked pydbus
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            assert manager.adapter_path == "/org/bluez/hci0"
            assert manager.bus is not None
            assert manager.adapter is not None
    
    def test_init_custom_adapter(self):
        """Test initialization with custom adapter name."""
        mock_pydbus = create_mock_pydbus_module()
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager(adapter_name="hci1")
            
            assert manager.adapter_path == "/org/bluez/hci1"
    
    def test_init_pydbus_not_available(self):
        """Test initialization fails when pydbus not available."""
        with patch.dict('sys.modules', {'pydbus': None}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                bt_module.BluetoothManager()
            
            assert "pydbus library not available" in str(exc_info.value)
    
    def test_init_adapter_not_found(self):
        """Test initialization fails when adapter not found."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_bus.set_get_should_fail("/org/bluez/hci0")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                bt_module.BluetoothManager()
            
            assert "Failed to initialize Bluetooth adapter" in str(exc_info.value)


class TestBluetoothManagerDiscovery:
    """Test device discovery methods."""
    
    def test_find_device_by_name_success(self):
        """Test successful device discovery by name."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            # Mock time.sleep to speed up tests
            with patch('time.sleep'):
                mac = manager.find_device_by_name("RTK_BASE_ROD", scan_timeout=1)
            
            assert mac == "98:D3:51:FE:FE:E4"
            assert not mock_bus.adapter.is_discovering  # Discovery stopped
    
    def test_find_device_by_name_not_found(self):
        """Test device discovery when device not found."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with patch('time.sleep'):
                mac = manager.find_device_by_name("NonExistent", scan_timeout=1)
            
            assert mac is None
            assert not mock_bus.adapter.is_discovering
    
    def test_find_device_by_name_discovery_fails(self):
        """Test device discovery when StartDiscovery fails."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_bus.adapter.set_discovery_should_fail(True)
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                with patch('time.sleep'):
                    manager.find_device_by_name("Test")
            
            assert "Device discovery failed" in str(exc_info.value)
    
    def test_find_device_by_mac_exists(self):
        """Test checking if device exists by MAC address."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            exists = manager.find_device_by_mac("98:D3:51:FE:FE:E4")
            
            assert exists is True
    
    def test_find_device_by_mac_not_exists(self):
        """Test checking if device exists when it doesn't."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            exists = manager.find_device_by_mac("00:11:22:33:44:55")
            
            assert exists is False


class TestBluetoothManagerPairing:
    """Test device pairing methods."""
    
    def test_pair_device_success(self):
        """Test successful device pairing."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.pair_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Paired is True
    
    def test_pair_device_already_paired(self):
        """Test pairing when device already paired."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.Paired = True
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.pair_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Paired is True
    
    def test_pair_device_fails(self):
        """Test pairing when pairing fails."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.set_pair_should_fail(True)
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                manager.pair_device("98:D3:51:FE:FE:E4")
            
            assert "Pairing failed" in str(exc_info.value)
    
    def test_trust_device_success(self):
        """Test successfully trusting a device."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.trust_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Trusted is True
    
    def test_trust_device_fails(self):
        """Test trusting device when it fails."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        # Don't add device - will cause failure
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                manager.trust_device("98:D3:51:FE:FE:E4")
            
            assert "Trust failed" in str(exc_info.value)


class TestBluetoothManagerConnection:
    """Test device connection methods."""
    
    def test_connect_device_success(self):
        """Test successful device connection."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.connect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Connected is True
    
    def test_connect_device_already_connected(self):
        """Test connecting when device already connected."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.Connected = True
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.connect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Connected is True
    
    def test_connect_device_fails(self):
        """Test connection when it fails."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.set_connect_should_fail(True)
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                manager.connect_device("98:D3:51:FE:FE:E4")
            
            assert "Connection failed" in str(exc_info.value)
    
    def test_disconnect_device_success(self):
        """Test successful device disconnection."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.Connected = True
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            result = manager.disconnect_device("98:D3:51:FE:FE:E4")
            
            assert result is True
            assert device.Connected is False
    
    def test_disconnect_device_fails(self):
        """Test disconnection when it fails."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        device = mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        device.set_disconnect_should_fail(True)
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                manager.disconnect_device("98:D3:51:FE:FE:E4")
            
            assert "Disconnection failed" in str(exc_info.value)


class TestBluetoothManagerHelpers:
    """Test helper methods."""
    
    def test_discover_rfcomm_channel(self):
        """Test RFCOMM channel discovery."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            channel = manager.discover_rfcomm_channel("98:D3:51:FE:FE:E4")
            
            # Currently returns 1 (SPP standard)
            assert channel == 1
    
    def test_ensure_device_ready_with_name(self):
        """Test ensure_device_ready with device name."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_bus.add_device("98:D3:51:FE:FE:E4", "RTK_BASE_ROD")
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with patch('time.sleep'):
                mac, channel = manager.ensure_device_ready(device_name="RTK_BASE_ROD")
            
            assert mac == "98:D3:51:FE:FE:E4"
            assert channel == 1
    
    def test_ensure_device_ready_device_not_found(self):
        """Test ensure_device_ready when device not found."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                with patch('time.sleep'):
                    manager.ensure_device_ready(device_name="NonExistent")
            
            assert "Device NonExistent not found" in str(exc_info.value)
    
    def test_ensure_device_ready_no_name_or_mac(self):
        """Test ensure_device_ready with no device name or MAC."""
        mock_pydbus = create_mock_pydbus_module()
        mock_bus = MockSystemBus()
        mock_pydbus.SystemBus = lambda: mock_bus
        
        with patch.dict('sys.modules', {'pydbus': mock_pydbus}):
            import importlib
            import src.sp_base_relay.core.bluetooth_manager as bt_module
            importlib.reload(bt_module)
            
            manager = bt_module.BluetoothManager()
            
            with pytest.raises(bt_module.BluetoothError) as exc_info:
                manager.ensure_device_ready()
            
            assert "Must provide either device_name or mac_address" in str(exc_info.value)
