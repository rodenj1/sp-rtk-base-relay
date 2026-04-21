"""Unit tests for Bluetooth input source.

Tests the BluetoothInputSource class which provides RTCM data reading
from GNSS receivers via Bluetooth SPP using native BlueZ D-Bus API.
"""

import socket
from unittest.mock import patch, MagicMock, Mock
import pytest

from src.sp_rtk_base_relay.core.bluetooth_manager import BluetoothManager
from src.sp_rtk_base_relay.core.input_sources.bluetooth_input import (
    BluetoothInputSource,
    BluetoothConfig,
)
from src.sp_rtk_base_relay.exceptions import InputSourceError


class TestBluetoothConfig:
    """Test BluetoothConfig dataclass."""
    
    def test_config_defaults(self):
        """Test default configuration values."""
        config = BluetoothConfig()
        
        assert config.device_name is None
        assert config.mac_address is None
        assert config.auto_pair is True
        assert config.auto_trust is True
        assert config.pin == "0000"
        assert config.adapter_name == "hci0"
        assert config.scan_timeout == 10
        assert config.read_timeout == 1.0
        assert config.connect_timeout == 10.0
    
    def test_config_custom_values(self):
        """Test custom configuration values."""
        config = BluetoothConfig(
            device_name="RTK_GPS_BASE",
            mac_address="00:11:22:33:44:55",
            auto_pair=False,
            adapter_name="hci1",
            scan_timeout=20,
        )
        
        assert config.device_name == "RTK_GPS_BASE"
        assert config.mac_address == "00:11:22:33:44:55"
        assert config.auto_pair is False
        assert config.adapter_name == "hci1"
        assert config.scan_timeout == 20


class TestBluetoothInputSourceInit:
    """Test BluetoothInputSource initialization."""
    
    def test_init_with_device_name(self):
        """Test initialization with device name."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        assert source.source_type == "Bluetooth"
        assert source.config == config
        assert source.bt_manager is None
        assert source.bt_socket is None
        assert source.connected_mac is None
        assert source.rfcomm_channel is None
    
    def test_init_with_mac_address(self):
        """Test initialization with MAC address."""
        config = BluetoothConfig(mac_address="00:11:22:33:44:55")
        source = BluetoothInputSource(config)
        
        assert source.config.mac_address == "00:11:22:33:44:55"
    
    def test_init_no_device_or_mac(self):
        """Test initialization fails without device name or MAC."""
        config = BluetoothConfig()
        
        with pytest.raises(InputSourceError) as exc_info:
            BluetoothInputSource(config)
        
        assert "device_name or mac_address must be specified" in str(exc_info.value)
    
    def test_init_invalid_scan_timeout(self):
        """Test initialization fails with invalid scan timeout."""
        config = BluetoothConfig(device_name="Test", scan_timeout=0)
        
        with pytest.raises(InputSourceError) as exc_info:
            BluetoothInputSource(config)
        
        assert "Invalid scan timeout" in str(exc_info.value)
    
    def test_init_invalid_read_timeout(self):
        """Test initialization fails with invalid read timeout."""
        config = BluetoothConfig(device_name="Test", read_timeout=0)
        
        with pytest.raises(InputSourceError) as exc_info:
            BluetoothInputSource(config)
        
        assert "Invalid read timeout" in str(exc_info.value)
    
    def test_init_invalid_connect_timeout(self):
        """Test initialization fails with invalid connect timeout."""
        config = BluetoothConfig(device_name="Test", connect_timeout=-1)
        
        with pytest.raises(InputSourceError) as exc_info:
            BluetoothInputSource(config)
        
        assert "Invalid connect timeout" in str(exc_info.value)


class TestBluetoothInputSourceConnection:
    """Test Bluetooth connection operations.
    
    These tests mock BluetoothManager methods to avoid asyncio.run() 
    conflicting with mocked socket.socket. The BluetoothManager methods
    are already fully tested in test_bluetooth_manager.py.
    """
    
    def test_connect_success_with_device_name(self):
        """Test successful connection using device name."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        # Pre-inject a mock manager with ensure_device_ready mocked
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            result = source.connect()
        
        assert result is True
        assert source.is_connected is True
        assert source.connected_mac == "00:11:22:33:44:55"
        assert source.rfcomm_channel == 1
        assert source.stats.connection_attempts == 1
        assert source.stats.successful_connections == 1
        mock_socket.connect.assert_called_once_with(("00:11:22:33:44:55", 1))
        mock_manager.ensure_device_ready.assert_called_once_with(
            device_name="RTK_GPS_BASE",
            mac_address=None
        )
    
    def test_connect_success_with_mac_address(self):
        """Test successful connection using MAC address."""
        config = BluetoothConfig(mac_address="00:11:22:33:44:55")
        source = BluetoothInputSource(config)
        
        # Pre-inject a mock manager
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            result = source.connect()
        
        assert result is True
        assert source.is_connected is True
        mock_manager.ensure_device_ready.assert_called_once_with(
            device_name=None,
            mac_address="00:11:22:33:44:55"
        )
    
    def test_connect_already_connected(self):
        """Test connect when already connected."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        source._connected = True
        
        result = source.connect()
        
        assert result is True
    
    def test_connect_device_not_found(self):
        """Test connection fails when device not found."""
        from src.sp_rtk_base_relay.core.bluetooth_manager import BluetoothError
        
        config = BluetoothConfig(device_name="NonExistent")
        source = BluetoothInputSource(config)
        
        # Mock manager that raises BluetoothError for device not found
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.side_effect = BluetoothError(
            "Device NonExistent not found"
        )
        source.bt_manager = mock_manager
        
        with pytest.raises(InputSourceError) as exc_info:
            source.connect()
        
        assert "Device NonExistent not found" in str(exc_info.value)
        assert source.is_connected is False
    
    def test_connect_socket_fails(self):
        """Test connection fails when socket connection fails."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        # Mock manager succeeds, but socket fails
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        mock_socket.connect.side_effect = socket.error("Connection refused")
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            with pytest.raises(InputSourceError) as exc_info:
                source.connect()
        
        assert "Bluetooth socket connection failed" in str(exc_info.value)
        assert source.is_connected is False
    
    def test_disconnect(self):
        """Test disconnection."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        # Mock manager
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            source.connect()
            source.disconnect()
        
        assert source.is_connected is False
        assert source.bt_socket is None
        assert source.connected_mac is None
        assert source.rfcomm_channel is None
        mock_socket.close.assert_called_once()

    def test_disconnect_closes_bluetooth_manager(self):
        """Test disconnect calls bt_manager.close() to clean up D-Bus resources."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        # Mock manager
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            source.connect()
            assert source.bt_manager is not None
            source.disconnect()
        
        # bt_manager should be cleaned up (set to None after close)
        assert source.bt_manager is None
        mock_manager.close.assert_called_once()
        mock_manager.disconnect_device.assert_called_once_with("00:11:22:33:44:55")

    def test_disconnect_handles_close_error_gracefully(self):
        """Test disconnect handles bt_manager.close() error gracefully."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        # Mock manager that raises on close
        mock_manager = MagicMock(spec=BluetoothManager)
        mock_manager.ensure_device_ready.return_value = ("00:11:22:33:44:55", 1)
        mock_manager.close.side_effect = Exception("close failed")
        source.bt_manager = mock_manager
        
        mock_socket = Mock()
        
        with patch('src.sp_rtk_base_relay.core.input_sources.bluetooth_input.socket.socket', return_value=mock_socket):
            source.connect()
            # Should not raise despite close() error
            source.disconnect()
        
        assert source.bt_manager is None
        assert source.is_connected is False

    def test_disconnect_without_connected_mac_still_closes_manager(self):
        """Test disconnect closes manager even if connected_mac is None."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        mock_manager = MagicMock(spec=BluetoothManager)
        source.bt_manager = mock_manager
        source._connected = True
        source.connected_mac = None  # No MAC — disconnect_device should NOT be called
        
        source.disconnect()
        
        assert source.bt_manager is None
        mock_manager.close.assert_called_once()
        mock_manager.disconnect_device.assert_not_called()


class TestBluetoothInputSourceDataReading:
    """Test data reading operations."""
    
    def test_read_data_success(self):
        """Test successful data reading."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        
        # Simulate connected state
        source._connected = True
        mock_socket = Mock()
        mock_socket.recv.return_value = b"test_data"
        mock_socket.gettimeout.return_value = 1.0
        source.bt_socket = mock_socket
        
        data = source.read_data()
        
        assert data == b"test_data"
        assert source.stats.bytes_read == 9
        assert source.stats.messages_read == 1
        mock_socket.recv.assert_called_once_with(8192)
    
    def test_read_data_not_connected(self):
        """Test reading data when not connected."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        
        data = source.read_data()
        
        assert data is None
    
    def test_read_data_no_socket(self):
        """Test reading data when socket is None."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        source._connected = True
        source.bt_socket = None
        
        data = source.read_data()
        
        assert data is None
    
    def test_read_data_timeout(self):
        """Test reading data with timeout (no data available)."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        source._connected = True
        mock_socket = Mock()
        mock_socket.recv.side_effect = socket.timeout()
        mock_socket.gettimeout.return_value = 1.0
        source.bt_socket = mock_socket
        
        data = source.read_data()
        
        assert data is None
    
    def test_read_data_socket_closed(self):
        """Test reading when socket closed by remote."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        source._connected = True
        mock_socket = Mock()
        mock_socket.recv.return_value = b""  # Empty = closed
        mock_socket.gettimeout.return_value = 1.0
        source.bt_socket = mock_socket
        
        data = source.read_data()
        
        assert data is None
        assert source.is_connected is False  # Error state
    
    def test_read_data_socket_error(self):
        """Test reading with socket error."""
        config = BluetoothConfig(device_name="Test")
        source = BluetoothInputSource(config)
        source._connected = True
        mock_socket = Mock()
        mock_socket.recv.side_effect = socket.error("Read error")
        mock_socket.gettimeout.return_value = 1.0
        source.bt_socket = mock_socket
        
        data = source.read_data()
        
        assert data is None
        assert source.stats.read_errors == 1
        assert source.is_connected is False
    
class TestBluetoothInputSourceInfo:
    """Test connection info and statistics."""
    
    def test_get_connection_info_disconnected(self):
        """Test connection info when disconnected."""
        config = BluetoothConfig(
            device_name="RTK_GPS_BASE",
            mac_address="00:11:22:33:44:55"
        )
        source = BluetoothInputSource(config)
        
        info = source.get_connection_info()
        
        assert info["device_name"] == "RTK_GPS_BASE"
        assert info["mac_address"] == "00:11:22:33:44:55"
        assert info["adapter"] == "hci0"
        assert "connected_mac" not in info
    
    def test_get_connection_info_connected(self):
        """Test connection info when connected."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        source._connected = True
        source.connected_mac = "00:11:22:33:44:55"
        source.rfcomm_channel = 1
        source.bt_socket = Mock()
        
        info = source.get_connection_info()
        
        assert info["connected_mac"] == "00:11:22:33:44:55"
        assert info["rfcomm_channel"] == 1
        assert info["socket_connected"] is True
    
    def test_get_bluetooth_statistics(self):
        """Test Bluetooth statistics retrieval."""
        config = BluetoothConfig(
            device_name="RTK_GPS_BASE",
            mac_address="00:11:22:33:44:55"
        )
        source = BluetoothInputSource(config)
        source._connected = True
        source.connected_mac = "00:11:22:33:44:55"
        source.rfcomm_channel = 1
        source.stats.bytes_read = 1024
        source.stats.messages_read = 10
        
        stats = source.get_bluetooth_statistics()
        
        assert stats["config"]["device_name"] == "RTK_GPS_BASE"
        assert stats["config"]["mac_address"] == "00:11:22:33:44:55"
        assert stats["connection"]["connected"] is True
        assert stats["connection"]["connected_mac"] == "00:11:22:33:44:55"
        assert stats["connection"]["rfcomm_channel"] == 1
        assert stats["data_flow"]["bytes_read"] == 1024
        assert stats["data_flow"]["messages_read"] == 10
    
    def test_str_representation(self):
        """Test string representation."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        str_repr = str(source)
        
        assert "Bluetooth" in str_repr
        assert "disconnected" in str_repr
    
    def test_repr_representation(self):
        """Test detailed representation."""
        config = BluetoothConfig(device_name="RTK_GPS_BASE")
        source = BluetoothInputSource(config)
        
        repr_str = repr(source)
        
        assert "BluetoothInputSource" in repr_str
        assert "type='Bluetooth'" in repr_str
        assert "connected=False" in repr_str
