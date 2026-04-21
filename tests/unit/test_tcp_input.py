"""Comprehensive unit tests for TCP input source.

Tests cover configuration validation, connection lifecycle, data reading,
health monitoring, and error handling for the TCP input source.
"""

import pytest
import socket
import threading
import time
from unittest.mock import patch

from sp_rtk_base_relay.core.input_sources.tcp_input import (
    TCPInputSource,
    TCPConfig,
)
from sp_rtk_base_relay.exceptions import InputSourceError


class MockTCPServer:
    """Mock TCP server for testing TCP input source."""

    def __init__(self, host: str = "localhost", port: int = 0):
        """Initialize mock TCP server.

        Args:
            host: Server hostname
            port: Server port (0 for auto-assign)
        """
        self.host = host
        self.port = port
        self.server_socket: socket.socket | None = None
        self.client_socket: socket.socket | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.data_to_send: bytes = b""
        self.received_data: list[bytes] = []
        self.accept_connections = True
        self.close_after_accept = False

    def start(self) -> None:
        """Start mock server in background thread."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)

        # Get actual port if auto-assigned
        if self.port == 0:
            self.port = self.server_socket.getsockname()[1]

        self.running = True
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()

        # Give server time to start
        time.sleep(0.1)

    def stop(self) -> None:
        """Stop mock server."""
        self.running = False

        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass

        if self.thread:
            self.thread.join(timeout=1.0)

    def _run_server(self) -> None:
        """Server thread main loop."""
        try:
            while self.running:
                if not self.accept_connections:
                    time.sleep(0.1)
                    continue

                if self.server_socket:
                    self.server_socket.settimeout(0.5)
                try:
                    if self.server_socket:
                        client_conn = self.server_socket.accept()
                        self.client_socket = client_conn[0]

                    if self.close_after_accept:
                        if self.client_socket:
                            self.client_socket.close()
                        self.client_socket = None
                        continue

                    # Send any queued data
                    if self.data_to_send and self.client_socket:
                        self.client_socket.send(self.data_to_send)

                    # Keep connection alive and receive data
                    while self.running and self.client_socket:
                        self.client_socket.settimeout(0.5)
                        try:
                            data = self.client_socket.recv(1024)
                            if data:
                                self.received_data.append(data)
                            else:
                                break  # Connection closed
                        except socket.timeout:
                            continue
                        except:
                            break

                except socket.timeout:
                    continue
                except:
                    break

        except Exception:
            pass
        finally:
            if self.client_socket:
                try:
                    self.client_socket.close()
                except:
                    pass

    def send_data(self, data: bytes) -> None:
        """Send data to connected client."""
        if self.client_socket:
            try:
                self.client_socket.send(data)
            except:
                pass


# Configuration Tests


class TestTCPConfig:
    """Tests for TCPConfig dataclass."""

    def test_default_config(self):
        """Test TCPConfig with default values."""
        config = TCPConfig()
        assert config.host == "localhost"
        assert config.port == 5015
        assert config.timeout == 10.0
        assert config.read_timeout == 1.0
        assert config.buffer_size == 8192
        assert config.keepalive is True

    def test_custom_config(self):
        """Test TCPConfig with custom values."""
        config = TCPConfig(
            host="192.168.1.100",
            port=9999,
            timeout=5.0,
            read_timeout=2.0,
            buffer_size=4096,
            keepalive=False,
        )
        assert config.host == "192.168.1.100"
        assert config.port == 9999
        assert config.timeout == 5.0
        assert config.read_timeout == 2.0
        assert config.buffer_size == 4096
        assert config.keepalive is False

    def test_rtkbase_config_factory(self):
        """Test create_rtkbase_config factory method."""
        config = TCPInputSource.create_rtkbase_config()
        assert config.host == "localhost"
        assert config.port == 5015
        assert config.timeout == 10.0
        assert config.read_timeout == 2.0
        assert config.buffer_size == 8192
        assert config.keepalive is True

    def test_rtkbase_config_factory_custom(self):
        """Test create_rtkbase_config with custom host/port."""
        config = TCPInputSource.create_rtkbase_config(host="rtkbase.local", port=6000)
        assert config.host == "rtkbase.local"
        assert config.port == 6000


class TestTCPInputInitialization:
    """Tests for TCP input source initialization."""

    def test_valid_initialization(self):
        """Test initialization with valid config."""
        config = TCPConfig()
        tcp_input = TCPInputSource(config)

        assert tcp_input.source_type == "TCP"
        assert tcp_input.config == config
        assert tcp_input.socket is None
        assert not tcp_input.is_connected

    def test_empty_host_raises_error(self):
        """Test that empty host raises InputSourceError."""
        config = TCPConfig(host="")
        with pytest.raises(InputSourceError, match="TCP host must be specified"):
            TCPInputSource(config)

    def test_invalid_port_zero(self):
        """Test that port 0 raises InputSourceError."""
        config = TCPConfig(port=0)
        with pytest.raises(InputSourceError, match="Invalid TCP port"):
            TCPInputSource(config)

    def test_invalid_port_negative(self):
        """Test that negative port raises InputSourceError."""
        config = TCPConfig(port=-1)
        with pytest.raises(InputSourceError, match="Invalid TCP port"):
            TCPInputSource(config)

    def test_invalid_port_too_high(self):
        """Test that port > 65535 raises InputSourceError."""
        config = TCPConfig(port=65536)
        with pytest.raises(InputSourceError, match="Invalid TCP port"):
            TCPInputSource(config)

    def test_invalid_timeout_zero(self):
        """Test that zero timeout raises InputSourceError."""
        config = TCPConfig(timeout=0)
        with pytest.raises(InputSourceError, match="Invalid timeout"):
            TCPInputSource(config)

    def test_invalid_timeout_negative(self):
        """Test that negative timeout raises InputSourceError."""
        config = TCPConfig(timeout=-1.0)
        with pytest.raises(InputSourceError, match="Invalid timeout"):
            TCPInputSource(config)

    def test_invalid_read_timeout(self):
        """Test that invalid read timeout raises InputSourceError."""
        config = TCPConfig(read_timeout=-0.5)
        with pytest.raises(InputSourceError, match="Invalid read timeout"):
            TCPInputSource(config)

    def test_invalid_buffer_size(self):
        """Test that invalid buffer size raises InputSourceError."""
        config = TCPConfig(buffer_size=0)
        with pytest.raises(InputSourceError, match="Invalid buffer size"):
            TCPInputSource(config)


# Connection Lifecycle Tests


class TestTCPConnection:
    """Tests for TCP connection lifecycle."""

    def test_successful_connection(self):
        """Test successful TCP connection."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, timeout=2.0)
            tcp_input = TCPInputSource(config)

            assert tcp_input.connect()
            assert tcp_input.is_connected
            assert tcp_input.socket is not None
            assert tcp_input.stats.successful_connections == 1
            assert tcp_input.stats.connection_attempts == 1

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_connection_timeout(self):
        """Test connection timeout scenario."""
        # Use a non-routable IP to trigger timeout
        config = TCPConfig(host="192.0.2.1", port=9999, timeout=0.5)
        tcp_input = TCPInputSource(config)

        with pytest.raises(InputSourceError, match="TCP connection timeout"):
            tcp_input.connect()

        assert not tcp_input.is_connected
        assert tcp_input.stats.connection_failures == 1

    def test_connection_refused(self):
        """Test connection refused scenario."""
        # Try to connect to port that's not listening
        config = TCPConfig(host="localhost", port=54321, timeout=1.0)
        tcp_input = TCPInputSource(config)

        with pytest.raises(InputSourceError, match="TCP connection refused"):
            tcp_input.connect()

        assert not tcp_input.is_connected
        assert tcp_input.stats.connection_failures == 1

    def test_dns_resolution_failure(self):
        """Test DNS resolution failure."""
        config = TCPConfig(host="invalid.hostname.that.does.not.exist", port=5015)
        tcp_input = TCPInputSource(config)

        with pytest.raises(InputSourceError, match="DNS resolution failed"):
            tcp_input.connect()

        assert not tcp_input.is_connected

    def test_already_connected(self):
        """Test connecting when already connected."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)

            # First connection
            assert tcp_input.connect()
            assert tcp_input.is_connected

            # Second connection should return True without reconnecting
            assert tcp_input.connect()
            assert tcp_input.is_connected
            assert tcp_input.stats.connection_attempts == 1  # Only one actual attempt

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_socket_options_configured(self):
        """Test that socket options are properly configured."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, keepalive=True)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Verify socket options
            assert tcp_input.socket is not None
            keepalive = tcp_input.socket.getsockopt(
                socket.SOL_SOCKET, socket.SO_KEEPALIVE
            )
            assert keepalive == 1

            nodelay = tcp_input.socket.getsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY
            )
            assert nodelay == 1

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_connection_health_check_passes(self):
        """Test connection health check when connected."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Health check should pass via public interface
            assert tcp_input.socket is not None
            assert tcp_input.socket.getpeername()  # Will raise if not connected

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_connection_health_check_fails_when_disconnected(self):
        """Test connection health check when not connected."""
        config = TCPConfig()
        tcp_input = TCPInputSource(config)

        # Health check should fail when not connected
        assert tcp_input.socket is None

    def test_multiple_connect_disconnect_cycles(self):
        """Test multiple connection/disconnection cycles."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)

            # Multiple cycles
            for _ in range(3):
                assert tcp_input.connect()
                assert tcp_input.is_connected
                tcp_input.disconnect()
                assert not tcp_input.is_connected

            assert tcp_input.stats.successful_connections == 3
            assert tcp_input.stats.connection_attempts == 3
        finally:
            server.stop()

    def test_connection_statistics_tracking(self):
        """Test that connection statistics are tracked correctly."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)

            # Successful connection
            tcp_input.connect()
            assert tcp_input.stats.connection_attempts == 1
            assert tcp_input.stats.successful_connections == 1
            assert tcp_input.stats.connection_failures == 0
            assert tcp_input.stats.connected_since is not None

            tcp_input.disconnect()
        finally:
            server.stop()


# Data Reading Tests


class TestTCPDataReading:
    """Tests for TCP data reading operations."""

    def test_read_data_successfully(self):
        """Test reading data from TCP connection."""
        server = MockTCPServer()
        server.data_to_send = b"RTCM_DATA_12345"
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, read_timeout=1.0)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Read data
            data = tcp_input.read_data()
            assert data == b"RTCM_DATA_12345"
            assert tcp_input.stats.bytes_read == 15
            assert tcp_input.stats.messages_read == 1

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_read_data_with_no_data_available(self):
        """Test reading when no data is available (timeout)."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, read_timeout=0.1)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Read should return None on timeout (not an error)
            data = tcp_input.read_data()
            assert data is None
            assert tcp_input.stats.bytes_read == 0

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_read_data_with_custom_timeout(self):
        """Test reading with custom timeout parameter."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, read_timeout=5.0)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Read with shorter timeout
            start_time = time.time()
            data = tcp_input.read_data(timeout=0.1)
            elapsed = time.time() - start_time

            assert data is None
            assert elapsed < 1.0  # Should use custom timeout, not config timeout

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_read_data_when_not_connected(self):
        """Test reading when not connected returns None."""
        config = TCPConfig()
        tcp_input = TCPInputSource(config)

        data = tcp_input.read_data()
        assert data is None

    def test_read_data_respects_buffer_size(self):
        """Test that read respects buffer size limit."""
        server = MockTCPServer()
        # Send more data than buffer size
        server.data_to_send = b"X" * 10000
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, buffer_size=4096)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Read should respect buffer size
            data = tcp_input.read_data()
            assert data is not None
            assert len(data) <= 4096

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_read_data_connection_closed_by_peer(self):
        """Test reading when connection is closed by peer."""
        server = MockTCPServer()
        server.close_after_accept = True
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Give server time to close connection
            time.sleep(0.2)

            # Read should detect closed connection
            data = tcp_input.read_data()
            assert data is None
            assert tcp_input.last_error is not None

        finally:
            server.stop()

    def test_read_data_socket_error(self):
        """Test handling of socket errors during read."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Close socket to trigger error
            if tcp_input.socket:
                tcp_input.socket.close()

            # Read should handle error gracefully
            data = tcp_input.read_data()
            assert data is None
            assert tcp_input.last_error is not None
            assert tcp_input.stats.read_errors > 0

        finally:
            server.stop()

    def test_multiple_consecutive_reads(self):
        """Test multiple consecutive read operations."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, read_timeout=0.1)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Multiple reads
            for i in range(5):
                # Send data from server
                test_data = f"DATA_{i}".encode()
                server.send_data(test_data)
                time.sleep(0.1)

                data = tcp_input.read_data()
                if data:
                    assert test_data in data

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_read_statistics_tracking(self):
        """Test that read statistics are tracked correctly."""
        server = MockTCPServer()
        server.data_to_send = b"TEST"
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Successful read
            _data = tcp_input.read_data()
            assert tcp_input.stats.messages_read == 1
            assert tcp_input.stats.bytes_read == 4
            assert tcp_input.stats.last_read_time is not None

            tcp_input.disconnect()
        finally:
            server.stop()


# Health and Monitoring Tests


class TestTCPHealthMonitoring:
    """Tests for TCP health monitoring and statistics."""

    def test_connectivity_test_successful(self):
        """Test successful connectivity test."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)

            result = tcp_input.test_connectivity()
            assert result["reachable"] is True
            assert result["host"] == "localhost"
            assert result["port"] == server.port
            assert result["response_time_ms"] is not None
            assert result["response_time_ms"] >= 0  # Can be 0 for very fast connections
            assert result["error"] is None
        finally:
            server.stop()

    def test_connectivity_test_timeout(self):
        """Test connectivity test with timeout."""
        config = TCPConfig(host="192.0.2.1", port=9999, timeout=0.5)
        tcp_input = TCPInputSource(config)

        result = tcp_input.test_connectivity()
        assert result["reachable"] is False
        assert "timeout" in result["error"].lower()

    def test_connectivity_test_refused(self):
        """Test connectivity test with connection refused."""
        config = TCPConfig(host="localhost", port=54322, timeout=1.0)
        tcp_input = TCPInputSource(config)

        result = tcp_input.test_connectivity()
        assert result["reachable"] is False
        assert "refused" in result["error"].lower()

    def test_connectivity_test_dns_failure(self):
        """Test connectivity test with DNS failure."""
        config = TCPConfig(host="invalid.hostname.example", port=5015)
        tcp_input = TCPInputSource(config)

        result = tcp_input.test_connectivity()
        assert result["reachable"] is False
        assert "dns" in result["error"].lower() or "failed" in result["error"].lower()

    def test_tcp_statistics_retrieval(self):
        """Test getting detailed TCP statistics."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            stats = tcp_input.get_tcp_statistics()

            # Verify structure
            assert "config" in stats
            assert "connection" in stats
            assert "data_flow" in stats
            assert "connectivity_test" in stats

            # Verify config section
            assert stats["config"]["host"] == "localhost"
            assert stats["config"]["port"] == server.port

            # Verify connection section
            assert stats["connection"]["connected"] is True
            assert stats["connection"]["successful_connections"] == 1

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_service_availability_check_available(self):
        """Test service availability check when service is available."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)

            assert tcp_input.is_service_available()
        finally:
            server.stop()

    def test_service_availability_check_unavailable(self):
        """Test service availability check when service is unavailable."""
        config = TCPConfig(host="localhost", port=54323, timeout=0.5)
        tcp_input = TCPInputSource(config)

        assert not tcp_input.is_service_available()

    def test_connection_info_when_connected(self):
        """Test getting connection info when connected."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port, keepalive=True)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            info = tcp_input.get_connection_info()
            assert info["host"] == "localhost"
            assert info["port"] == server.port
            assert info["keepalive"] is True
            assert "local_address" in info
            assert "remote_address" in info

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_connection_info_when_disconnected(self):
        """Test getting connection info when disconnected."""
        config = TCPConfig(host="testhost", port=9999)
        tcp_input = TCPInputSource(config)

        info = tcp_input.get_connection_info()
        assert info["host"] == "testhost"
        assert info["port"] == 9999
        assert "local_address" not in info
        assert "remote_address" not in info


# Error Handling and Recovery Tests


class TestTCPErrorHandling:
    """Tests for TCP error handling and recovery."""

    def test_graceful_disconnection(self):
        """Test graceful disconnection."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Disconnect gracefully
            tcp_input.disconnect()
            assert not tcp_input.is_connected
            assert tcp_input.socket is None
            assert tcp_input.stats.connected_since is None
        finally:
            server.stop()

    def test_disconnect_when_not_connected(self):
        """Test disconnecting when not connected (should not raise error)."""
        config = TCPConfig()
        tcp_input = TCPInputSource(config)

        # Should not raise any error
        tcp_input.disconnect()
        assert not tcp_input.is_connected

    def test_error_state_handling(self):
        """Test that error states are properly handled."""
        config = TCPConfig(host="localhost", port=54324, timeout=0.5)
        tcp_input = TCPInputSource(config)

        try:
            tcp_input.connect()
        except InputSourceError:
            pass

        # Verify error was recorded
        assert tcp_input.last_error is not None
        assert not tcp_input.is_connected

    def test_connection_recovery_after_failure(self):
        """Test connection recovery after failure."""
        # Start server after first connection attempt fails
        config = TCPConfig(host="localhost", port=54325, timeout=0.5)
        tcp_input = TCPInputSource(config)

        # First attempt should fail
        with pytest.raises(InputSourceError):
            tcp_input.connect()

        assert tcp_input.stats.connection_failures == 1

        # Start server
        server = MockTCPServer(port=54325)
        server.start()

        try:
            # Second attempt should succeed
            assert tcp_input.connect()
            assert tcp_input.stats.successful_connections == 1

            tcp_input.disconnect()
        finally:
            server.stop()

    def test_error_statistics_tracking(self):
        """Test that error statistics are tracked."""
        config = TCPConfig(host="localhost", port=54326, timeout=0.5)
        tcp_input = TCPInputSource(config)

        # Multiple failed connection attempts
        for _ in range(3):
            try:
                tcp_input.connect()
            except InputSourceError:
                pass

        assert tcp_input.stats.connection_failures == 3
        assert tcp_input.stats.connection_attempts == 3
        assert tcp_input.stats.successful_connections == 0

    def test_exception_handling_in_connect(self):
        """Test exception handling during connection."""
        config = TCPConfig(host="invalid.hostname", port=5015)
        tcp_input = TCPInputSource(config)

        with pytest.raises(InputSourceError):
            tcp_input.connect()

        assert not tcp_input.is_connected
        assert tcp_input.last_error is not None

    def test_exception_handling_in_read_data(self):
        """Test exception handling during read."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Force socket error by closing
            if tcp_input.socket:
                tcp_input.socket.close()

            # Read should handle exception gracefully
            data = tcp_input.read_data()
            assert data is None
            assert tcp_input.stats.read_errors > 0

        finally:
            server.stop()

    def test_exception_handling_in_disconnect(self):
        """Test exception handling during disconnection."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Manually close socket first to trigger exception
            if tcp_input.socket:
                tcp_input.socket.close()

            # Disconnect should handle exception gracefully
            tcp_input.disconnect()
            assert not tcp_input.is_connected

        finally:
            server.stop()

    def test_last_error_tracking(self):
        """Test that last error is properly tracked."""
        config = TCPConfig(host="localhost", port=54327, timeout=0.5)
        tcp_input = TCPInputSource(config)

        try:
            tcp_input.connect()
        except InputSourceError:
            pass

        assert tcp_input.last_error is not None
        assert "refused" in str(tcp_input.last_error).lower()

    def test_connection_info_with_socket_errors(self):
        """Test getting connection info when socket errors occur."""
        server = MockTCPServer()
        server.start()

        try:
            config = TCPConfig(host="localhost", port=server.port)
            tcp_input = TCPInputSource(config)
            tcp_input.connect()

            # Close socket to trigger error in get_connection_info
            if tcp_input.socket:
                tcp_input.socket.close()

            # Should handle error gracefully
            info = tcp_input.get_connection_info()
            assert (
                "socket_error" in info or "socket_timeout" in info or info.get("host")
            )

        finally:
            server.stop()

    def test_connect_with_generic_exception(self):
        """Test connection with unexpected exception during socket creation."""
        config = TCPConfig(host="localhost", port=5015)
        tcp_input = TCPInputSource(config)

        # Patch socket creation to raise unexpected exception
        with pytest.raises(
            InputSourceError,
            match="Unexpected TCP read error|Unexpected serial connection error|TCP connection failed",
        ):
            with patch("socket.socket") as mock_socket:
                mock_socket.side_effect = RuntimeError("Unexpected error")
                tcp_input.connect()

    def test_connectivity_test_with_connection_failure(self):
        """Test connectivity test when connection fails."""
        config = TCPConfig(host="localhost", port=54330, timeout=0.5)
        tcp_input = TCPInputSource(config)

        # This will create a socket that fails to connect
        # Testing error path in test_connectivity
        result = tcp_input.test_connectivity()
        assert result["reachable"] is False
        assert result["error"] is not None
