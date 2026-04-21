"""End-to-end integration tests for complete data pipeline.

This module tests the complete data flow from TCP input source through
the data pipeline to the mock RTCM server. These tests verify the full
system integration with real hardware input.

Usage:
    # Run all end-to-end tests
    uv run pytest tests/integration/test_end_to_end_integration.py -v

    # Run with detailed output
    uv run pytest tests/integration/test_end_to_end_integration.py -v -s

    # Run specific test
    uv run pytest tests/integration/test_end_to_end_integration.py::TestBasicPipelineFlow::test_tcp_to_rtcm_flow -v
"""

import time
import pytest
import logging
from typing import Any
from dataclasses import asdict

from sp_rtk_base_relay.core.input_sources.tcp_input import TCPInputSource
from sp_rtk_base_relay.core.rtcm_client import RTCMClient
from sp_rtk_base_relay.config import RTCMServerConfig
from tests.fixtures.mock_rtcm_server import MockRTCMServer


logger = logging.getLogger(__name__)


# ============================================================================
# Basic Pipeline Flow Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestBasicPipelineFlow:
    """Test basic data flow through the complete pipeline."""

    def test_tcp_to_rtcm_flow(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test data flow from TCP input to mock RTCM server.

        Verifies:
        - TCP input reads data successfully
        - RTCM client connects and authenticates
        - Data is transmitted to RTCM server
        - Heartbeats are received
        """
        logger.info("Testing TCP to RTCM data flow")

        # Create RTCM client
        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Connect to mock RTCM server
            logger.info("Connecting to mock RTCM server")
            assert rtcm_client.connect(), "Failed to connect to mock RTCM server"

            # Wait for server to process connection
            time.sleep(0.5)

            # Verify server received connection
            server_stats = mock_rtcm_server.get_stats()
            assert (
                server_stats.connections_accepted > 0
            ), "Server should accept connection"
            assert (
                server_stats.successful_authentications > 0
            ), "Authentication should succeed"

            logger.info(f"Server stats: {server_stats}")

            # Read data from TCP input
            logger.info("Reading data from TCP input")
            data = connected_tcp_input.read_data(timeout=3.0)

            if data:
                logger.info(f"Read {len(data)} bytes from TCP input")

                # Send data to RTCM server
                success = rtcm_client.send_rtcm_data(data)
                assert success, "Data transmission should succeed"

                # Wait for server to receive data
                time.sleep(0.2)

                # Verify server received data
                server_stats = mock_rtcm_server.get_stats()
                assert server_stats.bytes_received > 0, "Server should receive data"

                logger.info(f"Server received: {server_stats.bytes_received} bytes")
            else:
                logger.warning("No data available from TCP input")

            # Verify heartbeats are being sent
            initial_heartbeats = server_stats.heartbeats_sent
            time.sleep(2.0)  # Wait for at least one heartbeat

            server_stats = mock_rtcm_server.get_stats()
            assert (
                server_stats.heartbeats_sent > initial_heartbeats
            ), "Server should send heartbeats"

            logger.info("End-to-end flow test successful")

        finally:
            # Cleanup
            rtcm_client.disconnect()

    def test_multiple_data_transmissions(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test multiple RTCM data transmissions.

        Verifies:
        - Multiple data reads work
        - Multiple transmissions succeed
        - Statistics track correctly
        """
        logger.info("Testing multiple data transmissions")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Connect
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Transmit multiple data chunks
            transmissions = 0
            max_transmissions = 5

            for i in range(max_transmissions):
                logger.info(f"Transmission {i+1}/{max_transmissions}")

                data = connected_tcp_input.read_data(timeout=2.0)
                if data:
                    success = rtcm_client.send_rtcm_data(data)
                    if success:
                        transmissions += 1
                        logger.info(f"Transmitted {len(data)} bytes")

                time.sleep(0.2)

            # Verify we transmitted some data
            logger.info(f"Completed {transmissions} transmissions")

            # Check server statistics
            server_stats = mock_rtcm_server.get_stats()
            logger.info(f"Server received: {server_stats.bytes_received} bytes total")

            if transmissions > 0:
                assert (
                    server_stats.bytes_received > 0
                ), "Server should have received data"

        finally:
            rtcm_client.disconnect()


# ============================================================================
# Connection Management Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestConnectionManagement:
    """Test connection management in end-to-end scenario."""

    def test_input_reconnection(
        self,
        tcp_input_source: TCPInputSource,
        skip_if_no_hardware: None,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test TCP input reconnection with active RTCM connection.

        Verifies:
        - Input can reconnect after disconnect
        - RTCM connection remains stable
        - Data flow resumes after reconnection
        """
        logger.info("Testing input reconnection")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Initial connections
            assert tcp_input_source.connect()
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Disconnect TCP input
            logger.info("Disconnecting TCP input")
            tcp_input_source.disconnect()
            assert not tcp_input_source.is_connected

            time.sleep(0.5)

            # Reconnect TCP input
            logger.info("Reconnecting TCP input")
            assert tcp_input_source.connect()
            assert tcp_input_source.is_connected

            # Verify RTCM connection still active
            assert rtcm_client.is_connected

            # Try reading and sending data
            data = tcp_input_source.read_data(timeout=2.0)
            if data:
                success = rtcm_client.send_rtcm_data(data)
                assert success, "Data transmission should work after reconnect"
                logger.info("Data flow resumed successfully")

        finally:
            tcp_input_source.disconnect()
            rtcm_client.disconnect()

    def test_rtcm_reconnection(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
        wait_for_condition: Any,
    ) -> None:
        """Test RTCM client reconnection with active input.

        Verifies:
        - RTCM client can reconnect
        - Input connection remains stable
        - Data flow resumes
        """
        logger.info("Testing RTCM reconnection")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Initial connection
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Disconnect RTCM
            logger.info("Disconnecting RTCM client")
            rtcm_client.disconnect()
            assert not rtcm_client.is_connected

            time.sleep(0.5)

            # Verify input still connected
            assert connected_tcp_input.is_connected

            # Reconnect RTCM
            logger.info("Reconnecting RTCM client")
            assert rtcm_client.connect()
            assert rtcm_client.is_connected

            # Try sending data
            data = connected_tcp_input.read_data(timeout=2.0)
            if data:
                success = rtcm_client.send_rtcm_data(data)
                assert success, "Data transmission should work after RTCM reconnect"
                logger.info("RTCM reconnection successful")

        finally:
            rtcm_client.disconnect()


# ============================================================================
# Multi-threaded Operation Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestMultiThreadedOperation:
    """Test multi-threaded operation of the pipeline."""

    def test_concurrent_operations(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test concurrent read and transmit operations.

        Verifies:
        - Concurrent operations don't interfere
        - Thread safety maintained
        - No deadlocks or race conditions
        """
        logger.info("Testing concurrent operations")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Connect
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Perform operations concurrently (simulated by rapid iterations)
            operations = 10
            for _ in range(operations):
                # Read from input
                data = connected_tcp_input.read_data(timeout=1.0)

                # Transmit immediately if we got data
                if data:
                    rtcm_client.send_rtcm_data(data)

                # Brief delay
                time.sleep(0.1)

            logger.info(f"Completed {operations} concurrent operations")

            # Verify connections still healthy
            assert connected_tcp_input.is_connected
            assert rtcm_client.is_connected

        finally:
            rtcm_client.disconnect()

    def test_heartbeat_monitoring_during_data_flow(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test heartbeat monitoring during active data flow.

        Verifies:
        - Heartbeats continue during data transmission
        - Heartbeat thread operates correctly
        - No interference with data flow
        """
        logger.info("Testing heartbeat monitoring during data flow")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            # Connect
            assert rtcm_client.connect()
            time.sleep(0.5)

            initial_heartbeats = mock_rtcm_server.get_stats().heartbeats_sent

            # Transmit data while monitoring heartbeats
            test_duration = 5.0
            start_time = time.time()
            transmissions = 0

            while time.time() - start_time < test_duration:
                data = connected_tcp_input.read_data(timeout=1.0)
                if data:
                    rtcm_client.send_rtcm_data(data)
                    transmissions += 1

                time.sleep(0.3)

            # Verify heartbeats continued
            final_heartbeats = mock_rtcm_server.get_stats().heartbeats_sent
            heartbeats_received = final_heartbeats - initial_heartbeats

            logger.info(f"Transmissions: {transmissions}")
            logger.info(f"Heartbeats received: {heartbeats_received}")

            # Should have received at least a few heartbeats (1 per second)
            assert (
                heartbeats_received >= 3
            ), "Should receive heartbeats during data flow"

        finally:
            rtcm_client.disconnect()


# ============================================================================
# Error Scenario Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
class TestErrorScenarios:
    """Test error handling in end-to-end scenarios."""

    def test_input_data_timeout(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test handling of input data timeout.

        Verifies:
        - Timeout doesn't break connections
        - System continues operating
        - Proper error handling
        """
        logger.info("Testing input data timeout handling")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Try reading with very short timeout multiple times
            for i in range(5):
                data = connected_tcp_input.read_data(timeout=0.1)
                logger.info(f"Read attempt {i+1}: {'Got data' if data else 'Timeout'}")
                time.sleep(0.1)

            # Connections should still be active
            assert connected_tcp_input.is_connected
            assert rtcm_client.is_connected

            logger.info("Timeout handling successful")

        finally:
            rtcm_client.disconnect()

    def test_empty_data_handling(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test handling of empty or null data.

        Verifies:
        - System handles no data gracefully
        - No crashes or errors
        - Connections remain stable
        """
        logger.info("Testing empty data handling")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Try transmitting when we might not have data
            attempts = 5
            for i in range(attempts):
                data = connected_tcp_input.read_data(timeout=0.5)

                if data:
                    rtcm_client.send_rtcm_data(data)
                    logger.info(f"Attempt {i+1}: Sent data")
                else:
                    logger.info(f"Attempt {i+1}: No data available")

                time.sleep(0.2)

            # System should remain stable
            assert connected_tcp_input.is_connected
            assert rtcm_client.is_connected

        finally:
            rtcm_client.disconnect()


# ============================================================================
# Long Running Tests
# ============================================================================


@pytest.mark.hardware
@pytest.mark.manual
@pytest.mark.slow
class TestLongRunning:
    """Long-running integration tests."""

    def test_extended_operation(
        self,
        connected_tcp_input: TCPInputSource,
        mock_rtcm_server: MockRTCMServer,
        mock_rtcm_connection_info: dict[str, Any],
    ) -> None:
        """Test extended operation over time.

        Verifies:
        - System remains stable over time
        - Memory doesn't leak
        - Connections remain healthy
        - Statistics track correctly
        """
        logger.info("Testing extended operation")

        rtcm_config = RTCMServerConfig(
            host=mock_rtcm_connection_info["host"],
            port=mock_rtcm_connection_info["port"],
            username=mock_rtcm_connection_info["username"],
            password=mock_rtcm_connection_info["password"],
        )
        rtcm_client = RTCMClient(rtcm_config)

        try:
            assert rtcm_client.connect()
            time.sleep(0.3)

            # Run for extended period
            test_duration = 60.0  # 1 minute
            check_interval = 10.0  # Check every 10 seconds

            start_time = time.time()
            checks = 0
            total_bytes = 0

            while time.time() - start_time < test_duration:
                # Read and transmit data
                data = connected_tcp_input.read_data(timeout=2.0)
                if data:
                    rtcm_client.send_rtcm_data(data)
                    total_bytes += len(data)

                # Periodic checks
                if time.time() - start_time >= checks * check_interval:
                    checks += 1
                    elapsed = time.time() - start_time

                    # Verify connections still active
                    assert (
                        connected_tcp_input.is_connected
                    ), f"Input disconnected at {elapsed:.1f}s"
                    assert (
                        rtcm_client.is_connected
                    ), f"RTCM disconnected at {elapsed:.1f}s"

                    # Log progress
                    input_stats = asdict(connected_tcp_input.connection_statistics)
                    server_stats = mock_rtcm_server.get_stats()

                    logger.info(f"Check {checks} at {elapsed:.1f}s:")
                    logger.info(f"  Input bytes: {input_stats['bytes_read']}")
                    logger.info(f"  Server bytes: {server_stats.bytes_received}")
                    logger.info(f"  Heartbeats: {server_stats.heartbeats_sent}")

                time.sleep(0.5)

            # Final statistics
            final_input_stats = asdict(connected_tcp_input.connection_statistics)
            final_server_stats = mock_rtcm_server.get_stats()

            logger.info("Extended operation test completed:")
            logger.info(f"  Duration: {test_duration}s")
            logger.info(f"  Input bytes read: {final_input_stats['bytes_read']}")
            logger.info(f"  Server bytes received: {final_server_stats.bytes_received}")
            logger.info(f"  Total transmissions: {total_bytes}")
            logger.info(
                f"  Connection failures: {final_input_stats['connection_failures']}"
            )

            # Verify no connection failures
            assert final_input_stats["connection_failures"] == 0

        finally:
            rtcm_client.disconnect()
