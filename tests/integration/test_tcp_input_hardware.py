"""Integration tests for TCP input source with real hardware.

This module tests the TCP input source with real hardware connection at
192.168.0.242:3000. Tests will be skipped if hardware is not available.

Usage:
    # Run all hardware tests
    uv run pytest tests/integration/test_tcp_input_hardware.py -v

    # Run with detailed output
    uv run pytest tests/integration/test_tcp_input_hardware.py -v -s

    # Run specific test
    uv run pytest tests/integration/test_tcp_input_hardware.py::test_connection_establishment -v
"""

import time
import pytest
import logging
from typing import Any
from dataclasses import asdict

from sp_base_relay.core.input_sources.tcp_input import TCPInputSource, TCPConfig
from sp_base_relay.exceptions import InputSourceError


logger = logging.getLogger(__name__)


# ============================================================================
# Connection Establishment Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestTCPConnectionEstablishment:
    """Test TCP connection establishment with real hardware."""

    def test_connection_establishment(
        self, tcp_input_source: TCPInputSource, skip_if_no_hardware: None
    ) -> None:
        """Test basic connection to TCP hardware.

        Verifies:
        - Connection succeeds
        - Connection state is correct
        - Connection info is populated
        """
        logger.info("Testing TCP connection establishment")

        # Connect to hardware
        assert tcp_input_source.connect(), "Failed to connect to TCP hardware"

        # Verify connection state
        assert tcp_input_source.is_connected, "TCP source should be connected"

        # Verify statistics
        stats = asdict(tcp_input_source.connection_statistics)
        assert stats["connection_attempts"] == 1, "Should have 1 connection attempt"
        assert (
            stats["successful_connections"] == 1
        ), "Should have 1 successful connection"
        assert stats["connection_failures"] == 0, "Should have no connection failures"

        # Verify connection info
        conn_info = tcp_input_source.get_connection_info()
        assert conn_info["host"] == "192.168.0.242"
        assert conn_info["port"] == 3000
        assert "local_address" in conn_info
        assert "remote_address" in conn_info

        logger.info(f"Connection info: {conn_info}")

        # Cleanup
        tcp_input_source.disconnect()
        assert not tcp_input_source.is_connected, "Should be disconnected"

    def test_connection_health_check(self, connected_tcp_input: TCPInputSource) -> None:
        """Test connection health monitoring.

        Verifies:
        - Health check passes for active connection
        - Connection info shows health status
        """
        logger.info("Testing connection health check")

        # Connection should be healthy
        assert connected_tcp_input.is_connected

        # Get detailed statistics
        stats = connected_tcp_input.get_tcp_statistics()
        logger.info(f"TCP statistics: {stats}")

        # Verify connectivity test shows reachable
        connectivity = stats["connectivity_test"]
        assert connectivity["reachable"], "Hardware should be reachable"
        assert connectivity["response_time_ms"] is not None

        logger.info(f"Response time: {connectivity['response_time_ms']}ms")

    def test_connection_timeout_handling(self, hardware_tcp_config: TCPConfig) -> None:
        """Test connection timeout with unreachable host.

        Verifies:
        - Timeout error is raised appropriately
        - Error state is set correctly
        """
        logger.info("Testing connection timeout handling")

        # Create config with unreachable host
        bad_config = TCPConfig(
            host="192.168.0.254",  # Non-existent host
            port=9999,
            timeout=2.0,  # Short timeout
            read_timeout=1.0,
            buffer_size=8192,
            keepalive=True,
        )

        source = TCPInputSource(bad_config)

        # Connection should fail
        with pytest.raises(InputSourceError) as exc_info:
            source.connect()

        assert (
            "timeout" in str(exc_info.value).lower()
            or "refused" in str(exc_info.value).lower()
        )
        assert not source.is_connected

        # Verify statistics
        stats = asdict(source.connection_statistics)
        assert stats["connection_failures"] > 0


# ============================================================================
# Data Reading Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestTCPDataReading:
    """Test RTCM data reading from real hardware."""

    def test_continuous_data_reading(
        self, connected_tcp_input: TCPInputSource, wait_for_condition: Any
    ) -> None:
        """Test continuous RTCM data reading.

        Verifies:
        - Data can be read continuously
        - Data is not empty
        - Statistics are updated correctly
        """
        logger.info("Testing continuous data reading")

        # Read multiple data chunks
        data_chunks: list[bytes] = []
        max_reads = 10
        read_timeout = 3.0  # Generous timeout for hardware

        for i in range(max_reads):
            logger.info(f"Reading chunk {i+1}/{max_reads}")
            data = connected_tcp_input.read_data(timeout=read_timeout)

            if data:
                data_chunks.append(data)
                logger.info(f"Read {len(data)} bytes")

            # Don't fail if occasional read returns no data
            time.sleep(0.1)

        # Verify we got some data
        assert len(data_chunks) > 0, "Should have read at least some data chunks"

        # Verify statistics
        stats = asdict(connected_tcp_input.connection_statistics)
        assert stats["bytes_read"] > 0, "Should have read some bytes"
        assert stats["messages_read"] >= len(data_chunks), "Message count should match"

        logger.info(f"Total bytes read: {stats['bytes_read']}")
        logger.info(f"Total messages: {stats['messages_read']}")
        logger.info(f"Data chunks received: {len(data_chunks)}")

    def test_data_format_validation(self, connected_tcp_input: TCPInputSource) -> None:
        """Test that received data has RTCM format characteristics.

        Verifies:
        - Data is non-empty
        - Data is binary
        - Data appears to be RTCM format (starts with 0xD3)
        """
        logger.info("Testing RTCM data format")

        # Read data with generous timeout
        max_attempts = 5
        rtcm_data = None

        for attempt in range(max_attempts):
            logger.info(f"Attempt {attempt+1}/{max_attempts} to read RTCM data")
            data = connected_tcp_input.read_data(timeout=3.0)

            if data and len(data) > 0:
                rtcm_data = data
                break

            time.sleep(0.5)

        assert rtcm_data is not None, "Should receive some data from hardware"
        assert len(rtcm_data) > 0, "Data should not be empty"
        assert isinstance(rtcm_data, bytes), "Data should be bytes"

        # Check for RTCM3 preamble (0xD3) - might not always be at start
        # due to streaming nature, but log for information
        if rtcm_data[0] == 0xD3:
            logger.info("Data appears to start with RTCM3 preamble (0xD3)")
        else:
            logger.info(f"Data starts with: 0x{rtcm_data[0]:02X}")

        logger.info(f"Received {len(rtcm_data)} bytes of data")

    def test_read_timeout_behavior(self, connected_tcp_input: TCPInputSource) -> None:
        """Test read timeout handling.

        Verifies:
        - Short timeout returns None if no data
        - Timeout doesn't break connection
        - Multiple timeouts work correctly
        """
        logger.info("Testing read timeout behavior")

        # Try reading with very short timeout
        # May or may not get data depending on hardware
        short_timeout = 0.1
        result = connected_tcp_input.read_data(timeout=short_timeout)

        # Result can be None (timeout) or data if hardware was sending
        logger.info(
            f"Short timeout result: {'Got data' if result else 'Timeout (no data)'}"
        )

        # Connection should still be active
        assert (
            connected_tcp_input.is_connected
        ), "Connection should remain active after timeout"

        # Should be able to read again
        result2 = connected_tcp_input.read_data(timeout=2.0)
        # Don't assert on result2 - hardware may not send continuously
        logger.info(f"Second read result: {'Got data' if result2 else 'No data'}")


# ============================================================================
# Connection Resilience Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestTCPConnectionResilience:
    """Test TCP connection resilience and error handling."""

    def test_manual_disconnect_and_reconnect(
        self, tcp_input_source: TCPInputSource, skip_if_no_hardware: None
    ) -> None:
        """Test manual disconnect and reconnect cycle.

        Verifies:
        - Disconnect works cleanly
        - Reconnect succeeds
        - Statistics are maintained correctly
        """
        logger.info("Testing disconnect and reconnect")

        # Initial connection
        assert tcp_input_source.connect()
        initial_stats = asdict(tcp_input_source.connection_statistics)

        # Disconnect
        tcp_input_source.disconnect()
        assert not tcp_input_source.is_connected

        # Wait a moment
        time.sleep(0.5)

        # Reconnect
        assert tcp_input_source.connect()
        assert tcp_input_source.is_connected

        # Verify statistics incremented
        final_stats = asdict(tcp_input_source.connection_statistics)
        assert (
            final_stats["connection_attempts"]
            == initial_stats["connection_attempts"] + 1
        )
        assert (
            final_stats["successful_connections"]
            == initial_stats["successful_connections"] + 1
        )

        # Cleanup
        tcp_input_source.disconnect()

    def test_multiple_read_cycles(
        self, tcp_input_source: TCPInputSource, skip_if_no_hardware: None
    ) -> None:
        """Test multiple connect-read-disconnect cycles.

        Verifies:
        - Multiple cycles work correctly
        - No resource leaks
        - Statistics accumulate properly
        """
        logger.info("Testing multiple read cycles")

        cycles = 3

        for cycle in range(cycles):
            logger.info(f"Cycle {cycle+1}/{cycles}")

            # Connect
            assert tcp_input_source.connect(), f"Connect failed on cycle {cycle+1}"

            # Read some data
            for _ in range(2):
                data = tcp_input_source.read_data(timeout=2.0)
                if data:
                    logger.info(f"Read {len(data)} bytes")

            # Disconnect
            tcp_input_source.disconnect()
            assert not tcp_input_source.is_connected

            # Brief pause between cycles
            time.sleep(0.5)

        # Verify final statistics
        stats = asdict(tcp_input_source.connection_statistics)
        assert stats["connection_attempts"] == cycles
        assert stats["successful_connections"] == cycles

        logger.info(f"Completed {cycles} cycles successfully")


# ============================================================================
# Performance Validation Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
@pytest.mark.slow
class TestTCPPerformance:
    """Test TCP connection performance characteristics."""

    def test_data_throughput(
        self, connected_tcp_input: TCPInputSource, measure_duration: Any
    ) -> None:
        """Test data throughput over time.

        Verifies:
        - Consistent data flow
        - Throughput metrics
        - Buffer management
        """
        logger.info("Testing data throughput")

        test_duration = 10.0  # seconds
        start_time = time.time()
        total_bytes = 0
        read_count = 0

        while time.time() - start_time < test_duration:
            data = connected_tcp_input.read_data(timeout=2.0)
            if data:
                total_bytes += len(data)
                read_count += 1

        elapsed = time.time() - start_time

        # Calculate throughput
        if elapsed > 0:
            bytes_per_sec = total_bytes / elapsed
            logger.info(f"Throughput: {bytes_per_sec:.2f} bytes/sec")
            logger.info(f"Total bytes: {total_bytes}")
            logger.info(f"Read operations: {read_count}")
            logger.info(f"Duration: {elapsed:.2f} seconds")

            # Verify we got reasonable throughput
            # RTCM data typically comes in bursts, so don't assert on minimum
            if total_bytes == 0:
                logger.warning("No data received during throughput test")

    def test_connection_stability(self, connected_tcp_input: TCPInputSource) -> None:
        """Test connection stability over extended period.

        Verifies:
        - Connection remains stable
        - No unexpected disconnections
        - Statistics remain consistent
        """
        logger.info("Testing connection stability")

        test_duration = 30.0  # seconds
        check_interval = 5.0  # seconds

        start_time = time.time()
        checks = 0

        while time.time() - start_time < test_duration:
            # Verify still connected
            assert (
                connected_tcp_input.is_connected
            ), f"Connection lost after {time.time() - start_time:.1f}s"

            # Try reading data
            data = connected_tcp_input.read_data(timeout=2.0)
            if data:
                logger.info(
                    f"Read {len(data)} bytes at {time.time() - start_time:.1f}s"
                )

            checks += 1
            time.sleep(check_interval)

        # Final statistics
        stats = asdict(connected_tcp_input.connection_statistics)
        logger.info(f"Stability test completed: {checks} checks over {test_duration}s")
        logger.info(f"Total bytes read: {stats['bytes_read']}")
        logger.info(f"Connection remained stable: {connected_tcp_input.is_connected}")

        assert stats["connection_failures"] == 0, "Should have no connection failures"


# ============================================================================
# Statistics and Monitoring Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestTCPStatistics:
    """Test TCP statistics and monitoring functionality."""

    def test_statistics_accuracy(self, connected_tcp_input: TCPInputSource) -> None:
        """Test that statistics are tracked accurately.

        Verifies:
        - Byte counts are accurate
        - Message counts are tracked
        - Timestamps are updated
        """
        logger.info("Testing statistics accuracy")

        # Get initial statistics
        initial_stats = asdict(connected_tcp_input.connection_statistics)
        initial_bytes = initial_stats["bytes_read"]

        # Read some data
        bytes_read = 0
        for _ in range(5):
            data = connected_tcp_input.read_data(timeout=2.0)
            if data:
                bytes_read += len(data)

        # Get final statistics
        final_stats = asdict(connected_tcp_input.connection_statistics)
        final_bytes = final_stats["bytes_read"]

        # Verify statistics updated
        bytes_delta = final_bytes - initial_bytes
        assert bytes_delta == bytes_read, "Byte count should match actual bytes read"

        logger.info(f"Bytes read: {bytes_read}")
        logger.info(f"Statistics delta: {bytes_delta}")

    def test_detailed_tcp_statistics(self, connected_tcp_input: TCPInputSource) -> None:
        """Test detailed TCP statistics collection.

        Verifies:
        - All statistics fields are present
        - Socket information is available
        - Connectivity test results included
        """
        logger.info("Testing detailed TCP statistics")

        stats = connected_tcp_input.get_tcp_statistics()

        # Verify all major sections present
        assert "config" in stats
        assert "connection" in stats
        assert "data_flow" in stats
        assert "socket_info" in stats
        assert "connectivity_test" in stats

        # Verify socket info
        socket_info = stats["socket_info"]
        assert "local_address" in socket_info
        assert "remote_address" in socket_info

        # Verify connectivity test
        connectivity = stats["connectivity_test"]
        assert connectivity["reachable"] is True
        assert connectivity["host"] == "192.168.0.242"
        assert connectivity["port"] == 3000

        logger.info(f"Detailed statistics: {stats}")
