"""TCP input source for RTKBase integration.

This module provides a TCP input source implementation for reading RTCM
correction data from RTKBase str2str_tcp service or other TCP-based
RTCM data sources.
"""

import logging
import socket
import time
from typing import Any
from dataclasses import dataclass

from .base_input import InputSource
from ...exceptions import InputSourceError


logger = logging.getLogger(__name__)


@dataclass
class TCPConfig:
    """TCP connection configuration parameters."""

    host: str = "localhost"
    port: int = 5015
    timeout: float = 10.0
    read_timeout: float = 1.0
    buffer_size: int = 8192
    keepalive: bool = True


class TCPInputSource(InputSource):
    """TCP input source for RTKBase str2str_tcp service.

    Provides RTCM data reading from TCP-based sources such as RTKBase
    str2str_tcp service. Supports connection management, automatic
    reconnection, and configurable timeouts.

    Note: This is designed for future RTKBase integration. Currently
    handles connection failures gracefully when no TCP source is available.
    """

    def __init__(self, config: TCPConfig):
        """Initialize TCP input source.

        Args:
            config: TCP connection configuration
        """
        super().__init__("TCP")
        self.config = config
        self.socket: socket.socket | None = None

        # Validate configuration
        self._validate_config()

        logger.info(f"Initialized TCP input source: {config.host}:{config.port}")

    def connect(self) -> bool:
        """Connect to TCP source.

        Returns:
            True if connection successful

        Raises:
            InputSourceError: If TCP configuration is invalid
        """
        if self.is_connected:
            logger.debug("TCP connection already established")
            return True

        try:
            logger.info(
                f"Connecting to TCP source {self.config.host}:{self.config.port}"
            )

            # Create TCP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.config.timeout)

            # Configure socket options
            if self.config.keepalive:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # Optimize for low latency
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            # Attempt connection
            self.socket.connect((self.config.host, self.config.port))

            # Set read timeout for data operations
            self.socket.settimeout(self.config.read_timeout)

            # Test basic connectivity
            if not self._test_connection_health():
                raise InputSourceError("TCP connection health check failed")

            self._update_connection_stats(True)
            return True

        except socket.timeout:
            error = InputSourceError(
                f"TCP connection timeout after {self.config.timeout}s to "
                f"{self.config.host}:{self.config.port}"
            )
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error
        except socket.gaierror as e:
            error = InputSourceError(
                f"DNS resolution failed for {self.config.host}: {e}"
            )
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error
        except ConnectionRefusedError:
            error = InputSourceError(
                f"TCP connection refused by {self.config.host}:{self.config.port}. "
                f"Is RTKBase str2str_tcp service running?"
            )
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error
        except Exception as e:
            error = InputSourceError(f"TCP connection failed: {e}")
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read RTCM data from TCP connection.

        Args:
            timeout: Read timeout in seconds (uses config default if None)

        Returns:
            Raw RTCM data bytes if available, None if no data or error
        """
        if not self.is_connected or not self.socket:
            return None

        try:
            # Use provided timeout or fall back to config timeout
            read_timeout = timeout if timeout is not None else self.config.read_timeout

            # Temporarily adjust socket timeout if different
            original_timeout = self.socket.gettimeout()
            if read_timeout != original_timeout:
                self.socket.settimeout(read_timeout)

            # Read data from TCP connection
            data = self.socket.recv(self.config.buffer_size)

            # Restore original timeout if we changed it
            if read_timeout != original_timeout:
                self.socket.settimeout(original_timeout)

            if data:
                self._update_read_stats(data)
                logger.debug(f"Read {len(data)} bytes from TCP connection")
                return data
            else:
                # No data or connection closed by peer
                logger.warning("TCP connection closed by peer")
                self._set_error_state(InputSourceError("TCP connection closed by peer"))
                return None

        except socket.timeout:
            # Timeout is not an error, just no data available
            self._update_read_stats(None)
            return None
        except socket.error as e:
            error = InputSourceError(f"TCP read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None
        except Exception as e:
            error = InputSourceError(f"Unexpected TCP read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None

    def disconnect(self) -> None:
        """Disconnect from TCP source and cleanup resources."""
        logger.info("Disconnecting from TCP source")

        if self.socket:
            try:
                # Graceful shutdown
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception as e:
                logger.warning(f"Error closing TCP socket: {e}")
            finally:
                self.socket = None

        self._connected = False
        self.stats.connected_since = None
        logger.info("TCP connection disconnected")

    def get_connection_info(self) -> dict[str, Any]:
        """Get TCP connection information.

        Returns:
            Dictionary with TCP connection details
        """
        info = {
            "host": self.config.host,
            "port": self.config.port,
            "timeout": self.config.timeout,
            "buffer_size": self.config.buffer_size,
            "keepalive": self.config.keepalive,
        }

        if self.socket and self.is_connected:
            try:
                local_addr = self.socket.getsockname()
                remote_addr = self.socket.getpeername()
                socket_timeout = self.socket.gettimeout()
                info["local_address"] = f"{local_addr[0]}:{local_addr[1]}"
                info["remote_address"] = f"{remote_addr[0]}:{remote_addr[1]}"
                info["socket_timeout"] = (
                    socket_timeout if socket_timeout is not None else "None"
                )
            except Exception as e:
                info["socket_error"] = str(e)

        return info

    def _validate_config(self) -> None:
        """Validate TCP connection configuration.

        Raises:
            InputSourceError: If configuration is invalid
        """
        if not self.config.host:
            raise InputSourceError("TCP host must be specified")

        if not (1 <= self.config.port <= 65535):
            raise InputSourceError(f"Invalid TCP port: {self.config.port}")

        if self.config.timeout <= 0:
            raise InputSourceError(f"Invalid timeout: {self.config.timeout}")

        if self.config.read_timeout <= 0:
            raise InputSourceError(f"Invalid read timeout: {self.config.read_timeout}")

        if self.config.buffer_size <= 0:
            raise InputSourceError(f"Invalid buffer size: {self.config.buffer_size}")

    def _test_connection_health(self) -> bool:
        """Test basic TCP connection health.

        Returns:
            True if connection appears healthy
        """
        if not self.socket:
            return False

        try:
            # Test socket status
            self.socket.getpeername()  # Will raise exception if not connected
            return True
        except Exception as e:
            logger.warning(f"TCP connection health check failed: {e}")
            return False

    def test_connectivity(self) -> dict[str, Any]:
        """Test connectivity to TCP source without establishing persistent connection.

        Returns:
            Dictionary with connectivity test results
        """
        test_result = {
            "host": self.config.host,
            "port": self.config.port,
            "reachable": False,
            "response_time_ms": None,
            "error": None,
        }

        try:
            start_time = time.time()

            # Create temporary socket for testing
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(self.config.timeout)

            try:
                test_socket.connect((self.config.host, self.config.port))

                response_time = (time.time() - start_time) * 1000
                test_result["reachable"] = True
                test_result["response_time_ms"] = int(round(response_time, 2))

                logger.info(
                    f"TCP connectivity test successful: {self.config.host}:{self.config.port} "
                    f"({response_time:.2f}ms)"
                )

            finally:
                test_socket.close()

        except socket.timeout:
            test_result["error"] = f"Connection timeout after {self.config.timeout}s"
            logger.warning(
                f"TCP connectivity test timeout: {self.config.host}:{self.config.port}"
            )
        except socket.gaierror as e:
            test_result["error"] = f"DNS resolution failed: {e}"
            logger.warning(f"TCP connectivity test DNS error: {e}")
        except ConnectionRefusedError:
            test_result["error"] = "Connection refused - service may not be running"
            logger.warning(
                f"TCP connectivity test refused: {self.config.host}:{self.config.port}"
            )
        except Exception as e:
            test_result["error"] = f"Connectivity test failed: {e}"
            logger.warning(f"TCP connectivity test error: {e}")

        return test_result

    def get_tcp_statistics(self) -> dict[str, Any]:
        """Get detailed TCP connection statistics and status.

        Returns:
            Dictionary with detailed TCP information
        """
        stats = {
            "config": {
                "host": self.config.host,
                "port": self.config.port,
                "timeout": self.config.timeout,
                "read_timeout": self.config.read_timeout,
                "buffer_size": self.config.buffer_size,
                "keepalive": self.config.keepalive,
            },
            "connection": {
                "connected": self.is_connected,
                "connection_attempts": self.stats.connection_attempts,
                "successful_connections": self.stats.successful_connections,
                "connection_failures": self.stats.connection_failures,
                "connected_since": self.stats.connected_since,
            },
            "data_flow": {
                "bytes_read": self.stats.bytes_read,
                "messages_read": self.stats.messages_read,
                "read_errors": self.stats.read_errors,
                "last_read_time": self.stats.last_read_time,
            },
            "last_error": str(self.last_error) if self.last_error else None,
        }

        if self.socket and self.is_connected:
            try:
                local_addr = self.socket.getsockname()
                remote_addr = self.socket.getpeername()
                socket_timeout = self.socket.gettimeout()
                socket_info = {
                    "local_address": f"{local_addr[0]}:{local_addr[1]}",
                    "remote_address": f"{remote_addr[0]}:{remote_addr[1]}",
                    "socket_timeout": (
                        socket_timeout if socket_timeout is not None else "None"
                    ),
                    "socket_family": self.socket.family.name,
                    "socket_type": self.socket.type.name,
                }
                stats["socket_info"] = socket_info
            except Exception as e:
                stats["socket_info"] = {"error": str(e)}

        # Add connectivity test results
        stats["connectivity_test"] = self.test_connectivity()

        return stats

    def is_service_available(self) -> bool:
        """Check if TCP service is available without connecting.

        Returns:
            True if service appears to be available
        """
        test_result = self.test_connectivity()
        return test_result["reachable"]

    @classmethod
    def create_rtkbase_config(
        cls, host: str = "localhost", port: int = 5015
    ) -> "TCPConfig":
        """Create a configuration optimized for RTKBase str2str_tcp service.

        Args:
            host: RTKBase server hostname (default: localhost)
            port: RTKBase str2str_tcp port (default: 5015)

        Returns:
            TCPConfig optimized for RTKBase
        """
        return TCPConfig(
            host=host,
            port=port,
            timeout=10.0,
            read_timeout=2.0,
            buffer_size=8192,
            keepalive=True,
        )
