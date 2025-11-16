"""Pytest configuration and fixtures for integration tests.

This module provides shared fixtures and configuration for integration testing,
including hardware connectivity checks, mock server setup, and test markers.
"""

import socket
import time
import pytest
import logging
from typing import Any
from collections.abc import Callable, Generator
from contextlib import contextmanager

from sp_base_relay.core.input_sources.tcp_input import TCPInputSource, TCPConfig
from tests.fixtures.mock_rtcm_server import MockRTCMServer


logger = logging.getLogger(__name__)


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config: Any) -> None:
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "hardware: mark test as requiring real hardware connection"
    )
    config.addinivalue_line(
        "markers", "manual: mark test as manual (run when hardware available)"
    )
    config.addinivalue_line("markers", "slow: mark test as slow running (> 5 seconds)")


# ============================================================================
# Hardware Configuration
# ============================================================================

# Real TCP hardware connection details
HARDWARE_TCP_HOST = "192.168.0.242"
HARDWARE_TCP_PORT = 3000
HARDWARE_TIMEOUT = 5.0  # Seconds to wait for hardware

# Mock RTCM server configuration
MOCK_RTCM_PORT = 50011  # Different from production (50010) and unit tests
MOCK_RTCM_HOST = "127.0.0.1"


@pytest.fixture
def hardware_tcp_config() -> TCPConfig:
    """Configuration for real TCP hardware connection.

    Returns:
        TCPConfig for 192.168.0.242:3000
    """
    return TCPConfig(
        host=HARDWARE_TCP_HOST,
        port=HARDWARE_TCP_PORT,
        timeout=10.0,
        read_timeout=2.0,
        buffer_size=8192,
        keepalive=True,
    )


@pytest.fixture(scope="session")
def mock_rtcm_config() -> dict[str, Any]:
    """Configuration for mock RTCM server.

    Returns:
        Dictionary with mock server configuration
    """
    return {
        "port": MOCK_RTCM_PORT,
        "bind_address": MOCK_RTCM_HOST,
        "heartbeat_interval": 1.0,
        "valid_credentials": {"your_mountpoint": "your_password", "testuser": "testpass"},
    }


# ============================================================================
# Hardware Availability Checking
# ============================================================================


def check_hardware_availability(
    host: str = HARDWARE_TCP_HOST,
    port: int = HARDWARE_TCP_PORT,
    timeout: float = HARDWARE_TIMEOUT,
) -> bool:
    """Check if TCP hardware is reachable.

    Args:
        host: Hardware hostname or IP
        port: Hardware port
        timeout: Connection timeout in seconds

    Returns:
        True if hardware is reachable
    """
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.settimeout(timeout)

        logger.info(f"Checking hardware availability: {host}:{port}")
        test_socket.connect((host, port))
        test_socket.close()

        logger.info(f"Hardware available at {host}:{port}")
        return True

    except socket.timeout:
        logger.warning(f"Hardware connection timeout: {host}:{port}")
        return False
    except ConnectionRefusedError:
        logger.warning(f"Hardware connection refused: {host}:{port}")
        return False
    except socket.gaierror as e:
        logger.warning(f"Hardware DNS resolution failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"Hardware availability check failed: {e}")
        return False


@pytest.fixture(scope="session")
def hardware_available() -> bool:
    """Session-scoped fixture to check hardware availability once.

    Returns:
        True if hardware is available
    """
    return check_hardware_availability()


@pytest.fixture
def skip_if_no_hardware(hardware_available: bool) -> None:
    """Skip test if hardware is not available.

    Args:
        hardware_available: Result from hardware_available fixture

    Raises:
        pytest.skip: If hardware is not available
    """
    if not hardware_available:
        pytest.skip(
            f"Hardware not available at {HARDWARE_TCP_HOST}:{HARDWARE_TCP_PORT}. "
            "These tests require real TCP hardware connection."
        )


# ============================================================================
# TCP Input Source Fixtures
# ============================================================================


@pytest.fixture
def tcp_input_source(
    hardware_tcp_config: TCPConfig,
) -> Generator[TCPInputSource, None, None]:
    """Create TCP input source for testing.

    Args:
        hardware_tcp_config: TCP configuration fixture

    Returns:
        TCPInputSource instance (not connected)
    """
    source = TCPInputSource(hardware_tcp_config)

    yield source

    # Cleanup: disconnect if connected
    if source.is_connected:
        source.disconnect()


@pytest.fixture
def connected_tcp_input(
    tcp_input_source: TCPInputSource, skip_if_no_hardware: None
) -> Generator[TCPInputSource, None, None]:
    """Create and connect TCP input source.

    Args:
        tcp_input_source: TCP input source fixture
        skip_if_no_hardware: Skip test if hardware unavailable

    Returns:
        Connected TCPInputSource instance

    Raises:
        pytest.skip: If connection fails
    """
    try:
        if tcp_input_source.connect():
            yield tcp_input_source
        else:
            pytest.skip("Failed to connect to TCP hardware")
    except Exception as e:
        pytest.skip(f"TCP connection failed: {e}")
    finally:
        if tcp_input_source.is_connected:
            tcp_input_source.disconnect()


# ============================================================================
# Mock RTCM Server Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def mock_rtcm_server(
    mock_rtcm_config: dict[str, Any],
) -> Generator[MockRTCMServer, None, None]:
    """Create and start mock RTCM server (session-scoped).

    The server is created once per test session and reused across all tests.
    This avoids port binding issues between tests.

    Args:
        mock_rtcm_config: Mock server configuration

    Yields:
        Running MockRTCMServer instance
    """
    server = MockRTCMServer(**mock_rtcm_config)
    server.start()

    # Wait for server to be ready
    time.sleep(0.2)

    logger.info(
        f"Mock RTCM server started on port {mock_rtcm_config['port']} (session-scoped)"
    )

    yield server

    # Cleanup: stop server at end of session
    server.stop()
    logger.info("Mock RTCM server stopped (end of session)")
    time.sleep(0.5)


@pytest.fixture
def mock_rtcm_connection_info(mock_rtcm_config: dict[str, Any]) -> dict[str, Any]:
    """Get connection information for mock RTCM server.

    Args:
        mock_rtcm_config: Mock server configuration

    Returns:
        Dictionary with connection details
    """
    return {
        "host": mock_rtcm_config["bind_address"],
        "port": mock_rtcm_config["port"],
        "username": "testuser",
        "password": "testpass",
    }


# ============================================================================
# Test Data Fixtures
# ============================================================================


@pytest.fixture
def sample_rtcm_data() -> bytes:
    """Generate sample RTCM message data.

    Returns:
        Sample RTCM message bytes
    """
    # Simple RTCM3 message structure for testing
    # Real messages will come from hardware, this is just for testing
    return bytes(
        [
            0xD3,
            0x00,
            0x13,  # RTCM3 preamble and length
            0x3E,
            0xD7,
            0x00,
            0x00,
            0x00,
            0x00,  # Message data
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x8C,
            0x8B,
            0x4C,  # CRC24
        ]
    )


# ============================================================================
# Logging Configuration
# ============================================================================


@pytest.fixture(scope="session", autouse=True)
def configure_integration_test_logging() -> None:
    """Configure logging for integration tests."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Set sp_base_relay logger to DEBUG for detailed output
    sp_logger = logging.getLogger("sp_base_relay")
    sp_logger.setLevel(logging.DEBUG)

    logger.info("Integration test logging configured")


# ============================================================================
# Test Utilities
# ============================================================================


@pytest.fixture
def wait_for_condition() -> Callable[[Callable[[], bool], float, float], bool]:
    """Utility fixture for waiting for conditions.

    Returns:
        Function to wait for a condition with timeout
    """

    def _wait(
        condition_func: Callable[[], bool], timeout: float = 5.0, interval: float = 0.1
    ) -> bool:
        """Wait for condition to become true.

        Args:
            condition_func: Function that returns bool
            timeout: Maximum time to wait in seconds
            interval: Check interval in seconds

        Returns:
            True if condition met within timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if condition_func():
                return True
            time.sleep(interval)
        return False

    return _wait


@pytest.fixture
def measure_duration() -> Callable[[], Any]:
    """Utility fixture for measuring operation duration.

    Returns:
        Context manager for duration measurement
    """

    @contextmanager
    def _measure() -> Generator[dict[str, float], None, None]:
        """Measure duration of code block."""
        start_time = time.time()
        result = {"duration": 0.0}
        try:
            yield result
        finally:
            result["duration"] = time.time() - start_time

    return _measure
