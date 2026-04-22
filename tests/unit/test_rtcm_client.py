# pyright: ignore[reportCallIssue]
"""Unit tests for RTCM client implementation.

Tests the RTCMClient class including connection management, authentication,
heartbeat monitoring, data transmission, and error handling.
"""

import socket
import threading
import time
from unittest.mock import Mock, patch

import pytest

from sp_rtk_base_relay.config import RTCMServerConfig
from sp_rtk_base_relay.core.connection_states import ConnectionState
from sp_rtk_base_relay.core.rtcm_client import (
    ConnectionStats,
    HeartbeatMonitor,
    RTCMClient,
)


# Simple inline mock server for testing
class SimpleMockRTCMServer:
    """Simplified mock RTCM server for unit tests."""

    def __init__(self, port: int = 50011):
        self.port = port
        self.running = False
        self.server_socket = None
        self.client_socket = None
        self.thread = None

    def start(self):
        """Start the mock server."""
        if self.running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Add timeout to prevent hanging
        self.server_socket.settimeout(0.5)
        self.server_socket.bind(("127.0.0.1", self.port))
        self.server_socket.listen(1)

        self.running = True
        self.thread = threading.Thread(target=self._accept_connection, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the mock server."""
        self.running = False

        # Close client socket first
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None

        # Wait for thread to finish with timeout
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.2)

    def _accept_connection(self):
        """Accept and handle client connection."""
        try:
            # Accept with timeout to avoid hanging
            if self.server_socket is None:
                return
            self.client_socket, _ = self.server_socket.accept()
            self.client_socket.settimeout(0.1)  # Short timeout for sends/receives

            # Handle authentication
            try:
                auth_data = self.client_socket.recv(1024)
                auth_str = auth_data.decode("ascii")

                if auth_str == "INIT:testuser:testpass*":
                    # Send success response
                    self.client_socket.sendall(b"$HB$")

                    # Send limited heartbeats (max 5 for testing)
                    heartbeat_count = 0
                    while self.running and heartbeat_count < 5:
                        try:
                            self.client_socket.sendall(b"$HB$")
                            heartbeat_count += 1
                            # Use shorter sleep and check running more frequently
                            for _ in range(10):  # 0.01 * 10 = 0.1 second total
                                if not self.running:
                                    break
                                time.sleep(0.01)
                        except:
                            break
                else:
                    # Send failure response for invalid auth
                    try:
                        self.client_socket.sendall(b"FAIL")
                    except:
                        pass
            except TimeoutError:
                pass
            except Exception:
                pass
        except TimeoutError:
            pass  # Accept timeout is normal when stopping
        except Exception:
            pass


# Test fixtures
@pytest.fixture
def rtcm_config() -> RTCMServerConfig:
    """Create test RTCM server configuration."""
    return RTCMServerConfig(
        host="127.0.0.1",
        port=50011,  # Different port for testing
        username="testuser",
        password="testpass",
        connection_timeout=5,
        read_timeout=10,
        heartbeat_timeout=30,
        retry_initial_delay=1,
        retry_max_delay=60,
        retry_multiplier=2.0,
    )


@pytest.fixture
def mock_server():  # type: ignore[misc]
    """Create and start mock RTCM server for testing."""
    server = SimpleMockRTCMServer(port=50011)
    server.start()
    time.sleep(0.05)  # Reduced startup wait
    yield server
    server.stop()
    time.sleep(0.05)  # Allow cleanup to complete


class TestConnectionStats:
    """Test cases for ConnectionStats dataclass."""

    def test_connection_stats_initialization(self):
        """Test ConnectionStats initializes with correct defaults."""
        stats = ConnectionStats()

        assert stats.connection_attempts == 0
        assert stats.successful_connections == 0
        assert stats.authentication_failures == 0
        assert stats.heartbeat_timeouts == 0
        assert stats.bytes_sent == 0
        assert stats.messages_sent == 0
        assert stats.last_heartbeat_time == 0.0
        assert stats.connected_since is None
        assert stats.current_retry_delay == 0

    def test_connection_stats_modification(self):
        """Test ConnectionStats fields can be modified."""
        stats = ConnectionStats()

        stats.connection_attempts = 5
        stats.successful_connections = 3
        stats.bytes_sent = 1024
        stats.messages_sent = 10

        assert stats.connection_attempts == 5
        assert stats.successful_connections == 3
        assert stats.bytes_sent == 1024
        assert stats.messages_sent == 10


class TestHeartbeatMonitor:
    """Test cases for HeartbeatMonitor class."""

    def test_heartbeat_monitor_initialization(self):
        """Test HeartbeatMonitor initializes correctly."""
        monitor = HeartbeatMonitor(timeout_seconds=30)

        assert monitor.timeout_seconds == 30
        assert monitor.last_heartbeat == 0.0
        assert monitor.running is False
        assert monitor.thread is None

    def test_heartbeat_monitor_update_heartbeat(self):
        """Test updating heartbeat timestamp."""
        monitor = HeartbeatMonitor()

        # Initially no heartbeat
        assert monitor.last_heartbeat == 0.0
        assert monitor.time_since_heartbeat() == 0.0

        # Update heartbeat
        monitor.update_heartbeat()

        assert monitor.last_heartbeat > 0
        assert monitor.time_since_heartbeat() >= 0
        assert monitor.time_since_heartbeat() < 1.0  # Should be very recent

    def test_heartbeat_timeout_detection(self):
        """Test heartbeat timeout detection."""
        monitor = HeartbeatMonitor(timeout_seconds=1)

        # No timeout initially
        assert not monitor.is_timeout()

        # Set old heartbeat
        monitor.last_heartbeat = time.time() - 2.0  # 2 seconds ago

        # Should detect timeout
        assert monitor.is_timeout()
        assert monitor.time_since_heartbeat() > 1.0

    @patch("socket.socket")
    def test_heartbeat_monitor_start_stop(self, mock_socket_class: Mock) -> None:  # type: ignore[misc]
        """Test starting and stopping heartbeat monitor."""
        mock_socket = Mock()
        mock_socket.recv.side_effect = [
            b"$HB$",
            TimeoutError(),
            b"",
        ]  # Heartbeat then timeout then disconnect

        monitor = HeartbeatMonitor(timeout_seconds=30)
        callback = Mock()

        # Start monitor
        monitor.start(mock_socket, callback)

        assert monitor.running is True
        assert monitor.thread is not None

        # Allow some processing but keep it short
        time.sleep(0.05)

        # Stop monitor immediately
        monitor.stop()

        assert monitor.running is False

        # Ensure thread is actually stopped
        if monitor.thread:
            monitor.thread.join(timeout=0.1)


class TestRTCMClient:
    """Test cases for RTCMClient class."""

    def test_rtcm_client_initialization(self, rtcm_config: RTCMServerConfig) -> None:
        """Test RTCMClient initializes correctly."""
        client = RTCMClient(rtcm_config)

        assert client.config == rtcm_config
        assert client.socket is None
        assert client.state == ConnectionState.DISCONNECTED
        assert isinstance(client.stats, ConnectionStats)
        assert client.heartbeat_monitor is not None
        assert client._current_retry_delay == rtcm_config.retry_initial_delay  # type: ignore[reportPrivateUsage]

    def test_connection_properties(self, rtcm_config: RTCMServerConfig) -> None:
        """Test connection state properties."""
        client = RTCMClient(rtcm_config)

        # Initially disconnected
        assert client.connection_state == ConnectionState.DISCONNECTED
        assert not client.is_connected
        assert client.should_retry()

        # Simulate connected state
        with client._lock:  # type: ignore[reportPrivateUsage]
            client.state = ConnectionState.CONNECTED

        assert client.connection_state == ConnectionState.CONNECTED
        assert client.is_connected
        assert not client.should_retry()

    def test_connection_statistics(self, rtcm_config: RTCMServerConfig) -> None:
        """Test connection statistics retrieval."""
        client = RTCMClient(rtcm_config)

        stats = client.connection_statistics
        assert isinstance(stats, ConnectionStats)
        assert stats.current_retry_delay == rtcm_config.retry_initial_delay

    @patch("socket.socket")
    def test_successful_connection_and_authentication(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test successful connection and authentication flow."""
        # Setup mock socket
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        mock_socket.recv.return_value = b"$HB$"  # Authentication success

        client = RTCMClient(rtcm_config)

        try:
            # Test connection
            result = client.connect()

            assert result is True
            assert client.connection_state == ConnectionState.CONNECTED
            assert client.stats.connection_attempts == 1
            assert client.stats.successful_connections == 1

            # Verify socket configuration
            mock_socket.setsockopt.assert_any_call(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
            )
            mock_socket.setsockopt.assert_any_call(
                socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1
            )

            # Verify connection and timeouts
            mock_socket.connect.assert_called_once_with(
                (rtcm_config.host, rtcm_config.port)
            )
            mock_socket.settimeout.assert_any_call(rtcm_config.connection_timeout)
            mock_socket.settimeout.assert_any_call(rtcm_config.read_timeout)

            # Verify authentication
            expected_auth = f"INIT:{rtcm_config.username}:{rtcm_config.password}*"
            mock_socket.sendall.assert_called_with(expected_auth.encode("ascii"))
            # The recv call is for authentication response, but heartbeat monitor also calls recv
            assert mock_socket.recv.call_count >= 1
        finally:
            # CRITICAL: Clean up HeartbeatMonitor thread
            client.disconnect()

    @patch("socket.socket")
    def test_authentication_failure(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test authentication failure handling."""
        # Setup mock socket
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        mock_socket.recv.return_value = b"FAIL"  # Authentication failure

        client = RTCMClient(rtcm_config)

        # Test connection
        result = client.connect()

        assert result is False
        assert client.connection_state == ConnectionState.ERROR
        assert client.stats.connection_attempts == 1
        assert client.stats.successful_connections == 0
        assert client.stats.authentication_failures == 1

        # Socket should be closed after failure
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_connection_timeout(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test connection timeout handling."""
        # Setup mock socket to raise timeout
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        mock_socket.connect.side_effect = TimeoutError()

        client = RTCMClient(rtcm_config)

        # Test connection
        result = client.connect()

        assert result is False
        assert client.connection_state == ConnectionState.ERROR
        assert client.stats.connection_attempts == 1
        assert client.stats.successful_connections == 0

        # Socket should be closed after failure
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_connection_refused(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test connection refused handling."""
        # Setup mock socket to raise connection refused
        mock_socket = Mock()
        mock_socket_class.return_value = mock_socket
        mock_socket.connect.side_effect = ConnectionRefusedError()

        client = RTCMClient(rtcm_config)

        # Test connection
        result = client.connect()

        assert result is False
        assert client.connection_state == ConnectionState.ERROR
        assert client.stats.connection_attempts == 1

        # Socket should be closed after failure
        mock_socket.close.assert_called_once()

    def test_disconnect(self, rtcm_config: RTCMServerConfig) -> None:
        """Test disconnection and cleanup."""
        client = RTCMClient(rtcm_config)

        # Simulate connected state
        mock_socket = Mock()
        client.socket = mock_socket
        with client._lock:  # type: ignore[reportPrivateUsage]
            client.state = ConnectionState.CONNECTED
            client.stats.connected_since = time.time()

        # Test disconnect
        client.disconnect()

        assert client.connection_state == ConnectionState.DISCONNECTED
        assert client.socket is None
        assert client.stats.connected_since is None

        # Socket should be closed
        mock_socket.close.assert_called_once()

    @patch("socket.socket")
    def test_send_rtcm_data_success(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test successful RTCM data transmission."""
        client = RTCMClient(rtcm_config)

        # Setup connected state
        mock_socket = Mock()
        client.socket = mock_socket
        with client._lock:  # type: ignore[reportPrivateUsage]
            client.state = ConnectionState.CONNECTED

        test_data = b"\xd3\x00\x13\x3e\xd7\x00\x00"  # Example RTCM data

        # Test data sending
        result = client.send_rtcm_data(test_data)

        assert result is True
        assert client.stats.bytes_sent == len(test_data)
        assert client.stats.messages_sent == 1

        # Verify socket call
        mock_socket.sendall.assert_called_once_with(test_data)

    def test_send_rtcm_data_not_connected(self, rtcm_config: RTCMServerConfig) -> None:
        """Test RTCM data sending when not connected."""
        client = RTCMClient(rtcm_config)

        test_data = b"\xd3\x00\x13\x3e\xd7\x00\x00"

        # Test data sending when not connected
        result = client.send_rtcm_data(test_data)

        assert result is False
        assert client.stats.bytes_sent == 0
        assert client.stats.messages_sent == 0

    @patch("socket.socket")
    def test_send_rtcm_data_socket_error(
        self, mock_socket_class: Mock, rtcm_config: RTCMServerConfig
    ) -> None:  # type: ignore[misc]
        """Test RTCM data sending with socket error."""
        client = RTCMClient(rtcm_config)

        # Setup connected state with failing socket
        mock_socket = Mock()
        mock_socket.sendall.side_effect = OSError("Connection lost")
        client.socket = mock_socket
        with client._lock:  # type: ignore[reportPrivateUsage]
            client.state = ConnectionState.CONNECTED

        test_data = b"\xd3\x00\x13\x3e\xd7\x00\x00"

        # Test data sending
        result = client.send_rtcm_data(test_data)

        assert result is False
        # Should trigger connection lost handling
        assert client.connection_state == ConnectionState.DISCONNECTED

    def test_retry_delay_logic(self, rtcm_config: RTCMServerConfig) -> None:
        """Test exponential backoff retry delay logic."""
        client = RTCMClient(rtcm_config)

        # Initial delay
        assert client.get_retry_delay() == rtcm_config.retry_initial_delay

        # Simulate connection loss and retry delay update
        client._update_retry_delay()  # type: ignore[reportPrivateUsage]
        expected_delay = min(
            int(rtcm_config.retry_initial_delay * rtcm_config.retry_multiplier),
            rtcm_config.retry_max_delay,
        )
        assert client.get_retry_delay() == expected_delay

        # Another update
        old_delay = client.get_retry_delay()
        client._update_retry_delay()  # type: ignore[reportPrivateUsage]
        new_expected = min(
            int(old_delay * rtcm_config.retry_multiplier), rtcm_config.retry_max_delay
        )
        assert client.get_retry_delay() == new_expected

    def test_retry_delay_reset(self, rtcm_config: RTCMServerConfig) -> None:
        """Test retry delay reset after successful connection."""
        client = RTCMClient(rtcm_config)

        # Increase retry delay
        client._update_retry_delay()  # type: ignore[reportPrivateUsage]
        client._update_retry_delay()  # type: ignore[reportPrivateUsage]
        assert client.get_retry_delay() > rtcm_config.retry_initial_delay

        # Reset delay (now a public method)
        client.reset_retry_delay()
        assert client.get_retry_delay() == rtcm_config.retry_initial_delay

    def test_retry_delay_max_cap(self, rtcm_config: RTCMServerConfig) -> None:
        """Test retry delay caps at maximum value."""
        client = RTCMClient(rtcm_config)

        # Update delay many times
        for _ in range(10):
            client._update_retry_delay()  # type: ignore[reportPrivateUsage]

        # Should cap at max delay
        assert client.get_retry_delay() == rtcm_config.retry_max_delay


class TestRTCMClientIntegration:
    """Integration tests using mock RTCM server."""

    def test_full_connection_cycle(
        self, rtcm_config: RTCMServerConfig, mock_server: SimpleMockRTCMServer
    ) -> None:
        """Test complete connection cycle with mock server."""
        client = RTCMClient(rtcm_config)

        # Test connection
        result = client.connect()

        assert result is True
        assert client.is_connected
        assert client.stats.successful_connections == 1

        # Wait for heartbeat
        time.sleep(0.2)

        # Test data sending
        test_data = b"\xd3\x00\x13\x3e\xd7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x8c\x8b"
        success = client.send_rtcm_data(test_data)
        assert success is True

        # Test disconnect
        client.disconnect()
        assert not client.is_connected

    def test_authentication_failure_with_mock_server(
        self, mock_server: SimpleMockRTCMServer
    ) -> None:
        """Test authentication failure with mock server."""
        # Use invalid credentials
        bad_config = RTCMServerConfig(
            host="127.0.0.1", port=50011, username="invaliduser", password="invalidpass"
        )

        client = RTCMClient(bad_config)

        # Test connection - should fail authentication
        result = client.connect()

        assert result is False
        assert not client.is_connected
        assert client.stats.authentication_failures == 1

    def test_heartbeat_monitoring_with_mock_server(
        self, rtcm_config: RTCMServerConfig, mock_server: SimpleMockRTCMServer
    ) -> None:
        """Test heartbeat monitoring with mock server."""
        client = RTCMClient(rtcm_config)

        # Connect to server
        result = client.connect()
        assert result is True

        # Wait for several heartbeats
        time.sleep(0.5)  # Server sends heartbeats every 0.1s

        # Check heartbeat was received
        assert client.heartbeat_monitor.last_heartbeat > 0
        assert client.heartbeat_monitor.time_since_heartbeat() < 1.0

        # Disconnect
        client.disconnect()
