# pyright: reportPrivateUsage=false
"""Additional edge case tests for RTCMClient to reach 90% coverage.

These tests target specific uncovered lines in rtcm_client.py.
"""

import time
from unittest.mock import Mock

from sp_rtk_base_relay.config import RTCMServerConfig
from sp_rtk_base_relay.core.connection_states import ConnectionState
from sp_rtk_base_relay.core.rtcm_client import RTCMClient


class TestRTCMClientConnectionErrors:
    """Test connection error scenarios in RTCMClient."""

    def test_connect_dns_resolution_failure(self):
        """Test connection handles DNS resolution failure."""
        config = RTCMServerConfig(
            host="nonexistent.invalid.domain",
            port=50010,
            username="test",
            password="test",
            connection_timeout=1,
        )
        client = RTCMClient(config)

        # Should handle DNS error gracefully
        result = client.connect()

        assert result is False
        assert client.connection_state == ConnectionState.ERROR
        assert client.stats.connection_attempts == 1
        assert client.stats.successful_connections == 0

    def test_connect_connection_refused(self):
        """Test connection handles connection refused error."""
        # Use an IP that should refuse connection (loopback on unlikely port)
        config = RTCMServerConfig(
            host="127.0.0.1",
            port=9,  # Unlikely to be open
            username="test",
            password="test",
            connection_timeout=1,
        )
        client = RTCMClient(config)

        # Should handle connection refused
        result = client.connect()

        assert result is False
        assert client.stats.connection_attempts == 1

    def test_send_rtcm_data_socket_error(self):
        """Test send_rtcm_data handles socket errors."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up mock socket that raises error
        mock_socket = Mock()
        mock_socket.sendall = Mock(side_effect=OSError("Send failed"))

        client.socket = mock_socket
        client.state = ConnectionState.CONNECTED

        # Should handle socket error gracefully
        result = client.send_rtcm_data(b"test_data")

        assert result is False
        # Should have triggered connection lost handling
        assert client.socket is None

    def test_send_rtcm_data_unexpected_exception(self):
        """Test send_rtcm_data handles unexpected exceptions."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up mock socket that raises unexpected error
        mock_socket = Mock()
        mock_socket.sendall = Mock(side_effect=RuntimeError("Unexpected error"))

        client.socket = mock_socket
        client.state = ConnectionState.CONNECTED

        # Should handle unexpected error gracefully
        result = client.send_rtcm_data(b"test_data")

        assert result is False

    def test_authenticate_socket_timeout(self):
        """Test authentication handles socket timeout."""
        config = RTCMServerConfig(
            host="rtcm.example.com",
            port=50010,
            username="test",
            password="test",
            read_timeout=1,
        )
        client = RTCMClient(config)

        # Set up mock socket that times out on recv
        mock_socket = Mock()
        mock_socket.sendall = Mock()
        mock_socket.recv = Mock(side_effect=TimeoutError("Timeout"))

        client.socket = mock_socket
        client.state = ConnectionState.CONNECTING

        # Should handle timeout gracefully
        result = client._authenticate()

        assert result is False
        assert client.stats.authentication_failures == 1

    def test_authenticate_exception(self):
        """Test authentication handles unexpected exceptions."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up mock socket that raises error
        mock_socket = Mock()
        mock_socket.sendall = Mock(side_effect=RuntimeError("Auth error"))

        client.socket = mock_socket
        client.state = ConnectionState.CONNECTING

        # Should handle exception gracefully
        result = client._authenticate()

        assert result is False
        assert client.stats.authentication_failures == 1

    def test_cleanup_connection_socket_close_exception(self):
        """Test cleanup handles exception during socket close."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up mock socket that raises error on close
        mock_socket = Mock()
        mock_socket.close = Mock(side_effect=RuntimeError("Close failed"))

        client.socket = mock_socket
        client.state = ConnectionState.CONNECTED

        # Should handle close exception gracefully
        client._cleanup_connection()

        # Socket should be set to None despite exception
        assert client.socket is None
        assert client.state == ConnectionState.ERROR


class TestRTCMClientRetryLogic:
    """Test retry delay logic in RTCMClient."""

    def test_update_retry_delay_exponential_backoff(self):
        """Test _update_retry_delay implements exponential backoff."""
        config = RTCMServerConfig(
            host="rtcm.example.com",
            port=50010,
            username="test",
            password="test",
            retry_initial_delay=1,
            retry_max_delay=60,
            retry_multiplier=2.0,
        )
        client = RTCMClient(config)

        # Initial delay should be 1
        assert client._current_retry_delay == 1

        # First update: 1 * 2 = 2
        client._update_retry_delay()
        assert client._current_retry_delay == 2

        # Second update: 2 * 2 = 4
        client._update_retry_delay()
        assert client._current_retry_delay == 4

        # Third update: 4 * 2 = 8
        client._update_retry_delay()
        assert client._current_retry_delay == 8

    def test_update_retry_delay_max_limit(self):
        """Test _update_retry_delay respects maximum delay."""
        config = RTCMServerConfig(
            host="rtcm.example.com",
            port=50010,
            username="test",
            password="test",
            retry_initial_delay=32,
            retry_max_delay=60,
            retry_multiplier=2.0,
        )
        client = RTCMClient(config)
        client._current_retry_delay = 32

        # Update: 32 * 2 = 64, but max is 60
        client._update_retry_delay()
        assert client._current_retry_delay == 60

        # Should stay at max
        client._update_retry_delay()
        assert client._current_retry_delay == 60

    def test_reset_retry_delay(self):
        """Test _reset_retry_delay resets to initial value."""
        config = RTCMServerConfig(
            host="rtcm.example.com",
            port=50010,
            username="test",
            password="test",
            retry_initial_delay=1,
            retry_max_delay=60,
            retry_multiplier=2.0,
        )
        client = RTCMClient(config)

        # Increase delay
        client._current_retry_delay = 32

        # Reset should go back to initial (now a public method)
        client.reset_retry_delay()
        assert client._current_retry_delay == 1


class TestRTCMClientConnectionLost:
    """Test connection lost handling in RTCMClient."""

    def test_on_connection_lost_cleanup(self):
        """Test _on_connection_lost performs proper cleanup."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up connected state
        mock_socket = Mock()
        client.socket = mock_socket
        client.state = ConnectionState.CONNECTED
        client.stats.connected_since = time.time()

        # Trigger connection lost
        client._on_connection_lost()

        # Should have cleaned up
        assert client.socket is None
        assert client.state == ConnectionState.DISCONNECTED
        assert client.stats.connected_since is None
        assert client._current_retry_delay > config.retry_initial_delay

    def test_on_heartbeat_timeout(self):
        """Test _on_heartbeat_timeout updates statistics."""
        config = RTCMServerConfig(
            host="rtcm.example.com", port=50010, username="test", password="test"
        )
        client = RTCMClient(config)

        # Set up connected state
        mock_socket = Mock()
        client.socket = mock_socket
        client.state = ConnectionState.CONNECTED

        initial_timeouts = client.stats.heartbeat_timeouts

        # Trigger timeout
        client._on_heartbeat_timeout()

        # Should have incremented timeout counter
        assert client.stats.heartbeat_timeouts == initial_timeouts + 1
        # Should have triggered connection lost
        assert client.socket is None


class TestHeartbeatMonitorEdgeCases:
    """Test HeartbeatMonitor edge cases."""

    def test_stop_when_not_running(self):
        """Test stop when monitor is not running."""
        from sp_rtk_base_relay.core.rtcm_client import HeartbeatMonitor

        monitor = HeartbeatMonitor(timeout_seconds=30)

        # Should handle stop gracefully when not running
        monitor.stop()

        assert not monitor.running

    def test_start_when_already_running(self):
        """Test start returns early if already running."""
        from sp_rtk_base_relay.core.rtcm_client import HeartbeatMonitor

        monitor = HeartbeatMonitor(timeout_seconds=30)
        monitor.running = True

        mock_socket = Mock()
        callback = Mock()

        # Should return early without starting new thread
        monitor.start(mock_socket, callback)

        # Thread should not be created
        assert monitor.thread is None
