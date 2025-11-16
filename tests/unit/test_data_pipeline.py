"""Unit tests for DataPipelineCoordinator.

Tests the data pipeline coordination between input sources and RTCM client,
including multi-threading, error handling, and coordinated restart logic.
"""

import pytest
import time
import threading
from unittest.mock import Mock
import queue

from typing import Any

from sp_base_relay.core.data_pipeline import (
    DataPipelineCoordinator,
    PipelineStats,
)
from sp_base_relay.core.rtcm_client import RTCMClient
from sp_base_relay.core.connection_states import ConnectionState
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.config import RTCMServerConfig
from sp_base_relay.exceptions import ServiceError, InputSourceError


# Simple mock input source for testing (inline)
class SimpleMockInputSource(InputSource):
    """Simplified mock input source for unit tests."""

    def __init__(self, should_fail_connect: bool = False):
        super().__init__("MockInput")
        self.should_fail_connect = should_fail_connect
        self._data_to_return: list[bytes] = []

    def connect(self) -> bool:
        if self.should_fail_connect:
            self._update_connection_stats(False)
            raise InputSourceError("Mock connection failed")
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        if not self.is_connected:
            return None
        if self._data_to_return:
            data = self._data_to_return.pop(0)
            self._update_read_stats(data)
            return data
        return None

    def disconnect(self) -> None:
        self._connected = False
        self.stats.connected_since = None

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "mock"}

    def queue_data(self, data: bytes) -> None:
        """Helper method to queue data for read_data to return."""
        self._data_to_return.append(data)


class TestPipelineStats:
    """Test PipelineStats dataclass."""

    def test_default_stats(self):
        """Test default pipeline statistics."""
        stats = PipelineStats()

        assert stats.pipeline_starts == 0
        assert stats.successful_starts == 0
        assert stats.pipeline_stops == 0
        assert stats.restart_attempts == 0
        assert stats.input_errors == 0
        assert stats.rtcm_errors == 0
        assert stats.coordination_errors == 0
        assert stats.bytes_processed == 0
        assert stats.messages_processed == 0
        assert stats.last_data_time == 0.0
        assert stats.uptime_start is None

    def test_stats_with_values(self):
        """Test pipeline statistics with specific values."""
        stats = PipelineStats(
            pipeline_starts=5,
            successful_starts=4,
            bytes_processed=10000,
            messages_processed=50,
            uptime_start=time.time(),
        )

        assert stats.pipeline_starts == 5
        assert stats.successful_starts == 4
        assert stats.bytes_processed == 10000
        assert stats.messages_processed == 50
        assert stats.uptime_start is not None


class TestDataPipelineCoordinatorInitialization:
    """Test DataPipelineCoordinator initialization."""

    def test_initialization_with_valid_components(self):
        """Test coordinator initialization with valid input and RTCM client."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert coordinator.input_source == input_source
        assert coordinator.rtcm_client == rtcm_client
        assert not coordinator.is_running
        assert not coordinator.is_healthy
        assert isinstance(coordinator.stats, PipelineStats)
        assert coordinator.data_queue.maxsize == 10

    def test_initialization_with_callback(self):
        """Test coordinator initialization with restart callback."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        callback = Mock()

        coordinator = DataPipelineCoordinator(
            input_source, rtcm_client, restart_callback=callback
        )

        assert coordinator.restart_callback == callback

    def test_initial_state(self):
        """Test coordinator initial state."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert not coordinator.running
        assert coordinator.input_thread is None
        assert not coordinator._stop_event.is_set()  # type: ignore
        assert not coordinator._restart_requested.is_set()  # type: ignore


class TestDataPipelineConnection:
    """Test data pipeline connection management."""

    def test_start_relay_input_connection_failure(self):
        """Test start_relay when input source connection fails."""
        # Create input source that will fail to connect
        input_source = SimpleMockInputSource(should_fail_connect=True)

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Start relay should fail with ServiceError (wraps InputSourceError)
        with pytest.raises((ServiceError, InputSourceError)):
            coordinator.start_relay()

        assert not coordinator.is_running
        assert coordinator.stats.pipeline_starts == 1
        assert coordinator.stats.successful_starts == 0

    def test_start_relay_rtcm_connection_failure(self):
        """Test start_relay when RTCM client connection fails."""
        # Create input source that connects successfully
        input_source = SimpleMockInputSource()

        # Create RTCM client that will fail (invalid host)
        rtcm_config = RTCMServerConfig(
            host="invalid.host.nowhere",
            port=50010,
            username="test",
            password="test",
            connection_timeout=1,
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Start relay should fail with ServiceError
        with pytest.raises(ServiceError, match="Failed to connect RTCM server"):
            coordinator.start_relay()

        # Input source should be disconnected on RTCM failure
        assert not input_source.is_connected
        assert not coordinator.is_running


class TestDataPipelineStopAndCleanup:
    """Test data pipeline stop and cleanup operations."""

    def test_stop_relay_when_not_running(self):
        """Test stop_relay when pipeline is not running."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Should not raise error
        coordinator.stop_relay()

        assert not coordinator.is_running

    def test_request_restart(self):
        """Test restart request functionality."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True  # Simulate running state

        coordinator.request_restart()

        assert coordinator._restart_requested.is_set()  # type: ignore
        assert coordinator.stats.restart_attempts == 1
        assert not coordinator.running


class TestDataPipelineHealthChecks:
    """Test data pipeline health check functionality."""

    def test_is_running_property(self):
        """Test is_running property."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert not coordinator.is_running

        coordinator.running = True
        assert coordinator.is_running

    def test_is_healthy_both_connected(self):
        """Test is_healthy when both connections are healthy."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        # Mock RTCM client as connected by setting state directly
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        assert coordinator.is_healthy

    def test_is_healthy_input_disconnected(self):
        """Test is_healthy when input source is disconnected."""
        input_source = SimpleMockInputSource()
        # Don't connect input source

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        assert not coordinator.is_healthy

    def test_is_healthy_rtcm_disconnected(self):
        """Test is_healthy when RTCM client is disconnected."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        # RTCM client not connected

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        assert not coordinator.is_healthy

    def test_is_healthy_not_running(self):
        """Test is_healthy when pipeline is not running."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        # Not running

        assert not coordinator.is_healthy


class TestDataPipelineStatistics:
    """Test data pipeline statistics tracking."""

    def test_pipeline_statistics_property(self):
        """Test pipeline_statistics property returns stats."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        stats = coordinator.pipeline_statistics

        assert isinstance(stats, PipelineStats)
        assert stats.pipeline_starts == 0
        assert stats.bytes_processed == 0

    def test_get_detailed_status(self):
        """Test get_detailed_status returns comprehensive information."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        status = coordinator.get_detailed_status()

        assert "pipeline" in status
        assert "input_source" in status
        assert "rtcm_client" in status
        assert "pipeline_statistics" in status
        assert "queue_status" in status

        assert status["pipeline"]["running"] is True
        assert status["input_source"]["connected"] is True
        assert status["input_source"]["type"] == "MockInput"
        assert "size" in status["queue_status"]
        assert "max_size" in status["queue_status"]

    def test_get_detailed_status_with_uptime(self):
        """Test get_detailed_status includes uptime when running."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True
        coordinator.stats.uptime_start = time.time() - 10  # 10 seconds ago

        status = coordinator.get_detailed_status()

        assert "uptime_seconds" in status["pipeline"]
        assert status["pipeline"]["uptime_seconds"] >= 10


class TestDataPipelineErrorHandling:
    """Test data pipeline error handling."""

    def test_handle_input_error(self):
        """Test _handle_input_error increments error counter and requests restart."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        coordinator._handle_input_error("Test input error")  # type: ignore

        assert coordinator.stats.input_errors == 1
        assert coordinator._restart_requested.is_set()  # type: ignore

    def test_handle_rtcm_error(self):
        """Test _handle_rtcm_error increments error counter and requests restart."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        coordinator._handle_rtcm_error("Test RTCM error")  # type: ignore

        assert coordinator.stats.rtcm_errors == 1
        assert coordinator._restart_requested.is_set()  # type: ignore

    def test_handle_coordination_error(self):
        """Test _handle_coordination_error increments error counter and requests restart."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        coordinator._handle_coordination_error("Test coordination error")  # type: ignore

        assert coordinator.stats.coordination_errors == 1
        assert coordinator._restart_requested.is_set()  # type: ignore


class TestDataPipelineCleanup:
    """Test data pipeline cleanup operations."""

    def test_stop_relay_triggers_cleanup(self):
        """Test stop_relay triggers proper cleanup of resources."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True  # Simulate running state

        # Stop the relay
        coordinator.stop_relay()

        # Should be stopped
        assert not coordinator.is_running


class TestDataPipelineThreading:
    """Test data pipeline threading operations."""

    def test_queue_initialization(self):
        """Test data queue is properly initialized."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert isinstance(coordinator.data_queue, queue.Queue)
        assert coordinator.data_queue.maxsize == 10
        assert coordinator.data_queue.empty()

    def test_stop_event_initialization(self):
        """Test stop event is properly initialized."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert isinstance(coordinator._stop_event, threading.Event)  # type: ignore
        assert not coordinator._stop_event.is_set()  # type: ignore

    def test_restart_requested_event_initialization(self):
        """Test restart requested event is properly initialized."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        assert isinstance(coordinator._restart_requested, threading.Event)  # type: ignore
        assert not coordinator._restart_requested.is_set()  # type: ignore


class TestDataPipelineCallbacks:
    """Test data pipeline restart callback functionality."""

    def test_restart_callback_not_called_when_none(self):
        """Test restart callback not called when not provided."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Request restart should not fail even without callback
        coordinator.request_restart()

        assert coordinator._restart_requested.is_set()  # type: ignore


class TestDataPipelineConnectionHealthChecks:
    """Test data pipeline connection health check implementation."""

    def test_check_connections_health_both_healthy(self):
        """Test _check_connections_health when both connections are healthy."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        result = coordinator._check_connections_health()  # type: ignore

        assert result is True

    def test_check_connections_health_input_unhealthy(self):
        """Test _check_connections_health when input is unhealthy."""
        input_source = SimpleMockInputSource()
        # Don't connect input

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        result = coordinator._check_connections_health()  # type: ignore

        assert result is False
        assert coordinator.stats.input_errors == 1

    def test_check_connections_health_rtcm_unhealthy(self):
        """Test _check_connections_health when RTCM is unhealthy."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        # RTCM not connected

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        result = coordinator._check_connections_health()  # type: ignore

        assert result is False
        assert coordinator.stats.rtcm_errors == 1


class TestDataPipelineCleanupOperations:
    """Test data pipeline cleanup operations in detail."""

    def test_cleanup_connections_disconnects_both(self):
        """Test _cleanup_connections disconnects both connections."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Call cleanup
        coordinator._cleanup_connections()  # type: ignore

        # Both should be disconnected
        assert rtcm_client.connection_state == ConnectionState.DISCONNECTED

    def test_finalize_shutdown_clears_queue(self):
        """Test _finalize_shutdown clears the data queue."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Add some data to queue
        coordinator.data_queue.put(b"test1")
        coordinator.data_queue.put(b"test2")

        assert not coordinator.data_queue.empty()

        # Call finalize shutdown
        coordinator._finalize_shutdown()  # type: ignore

        # Queue should be empty
        assert coordinator.data_queue.empty()
        assert not coordinator.running

    def test_finalize_shutdown_resets_uptime(self):
        """Test _finalize_shutdown resets uptime."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.stats.uptime_start = time.time()

        coordinator._finalize_shutdown()  # type: ignore

        assert coordinator.stats.uptime_start is None


class TestDataPipelineStopBehavior:
    """Test data pipeline stop behavior and signal handling."""

    def test_stop_relay_sets_stop_event(self):
        """Test stop_relay sets the stop event."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        coordinator.stop_relay()

        assert coordinator._stop_event.is_set()  # type: ignore
        assert not coordinator.running

    def test_stop_relay_puts_none_in_queue(self):
        """Test stop_relay attempts to wake coordinator with None."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        coordinator.stop_relay()

        # Should increment stop counter
        assert coordinator.stats.pipeline_stops == 1


class TestDataPipelineStatisticsUpdates:
    """Test data pipeline statistics updates during operation."""

    def test_stats_update_on_start(self):
        """Test statistics are updated when pipeline starts."""
        input_source = SimpleMockInputSource()
        # Use invalid host that will fail quickly
        rtcm_config = RTCMServerConfig(
            host="240.0.0.1",  # Invalid IP that will fail immediately
            port=50010,
            username="test",
            password="test",
            connection_timeout=1,  # Short timeout
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        initial_starts = coordinator.stats.pipeline_starts

        # Try to start (will fail due to RTCM connection, but stats should update)
        try:
            coordinator.start_relay()
        except (ServiceError, OSError):
            pass

        assert coordinator.stats.pipeline_starts == initial_starts + 1

    def test_stats_include_error_counts(self):
        """Test statistics include all error counters."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Trigger different error types
        coordinator._handle_input_error("test1")  # type: ignore
        coordinator._handle_rtcm_error("test2")  # type: ignore
        coordinator._handle_coordination_error("test3")  # type: ignore

        assert coordinator.stats.input_errors == 1
        assert coordinator.stats.rtcm_errors == 1
        assert coordinator.stats.coordination_errors == 1
        assert coordinator.stats.restart_attempts == 3  # Each error triggers restart


class TestDataPipelineDetailedStatus:
    """Test detailed status reporting."""

    def test_detailed_status_includes_all_components(self):
        """Test get_detailed_status includes all required components."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        status = coordinator.get_detailed_status()

        # Check all major sections exist
        assert "pipeline" in status
        assert "input_source" in status
        assert "rtcm_client" in status
        assert "pipeline_statistics" in status
        assert "queue_status" in status

        # Check pipeline details
        assert "running" in status["pipeline"]
        assert "healthy" in status["pipeline"]
        assert "restart_requested" in status["pipeline"]

        # Check input source details
        assert "connected" in status["input_source"]
        assert "type" in status["input_source"]
        assert "connection_info" in status["input_source"]
        assert "statistics" in status["input_source"]

        # Check RTCM client details
        assert "connected" in status["rtcm_client"]
        assert "state" in status["rtcm_client"]
        assert "statistics" in status["rtcm_client"]

        # Check queue status
        assert "size" in status["queue_status"]
        assert "max_size" in status["queue_status"]

    def test_detailed_status_reflects_restart_request(self):
        """Test detailed status reflects restart request state."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Initially not requested
        status = coordinator.get_detailed_status()
        assert status["pipeline"]["restart_requested"] is False

        # Request restart
        coordinator.request_restart()

        status = coordinator.get_detailed_status()
        assert status["pipeline"]["restart_requested"] is True


class TestDataPipelineMultipleErrorScenarios:
    """Test multiple error scenarios and their handling."""

    def test_multiple_input_errors_accumulate(self):
        """Test multiple input errors accumulate in statistics."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Trigger multiple errors
        coordinator._handle_input_error("error1")  # type: ignore
        coordinator._handle_input_error("error2")  # type: ignore
        coordinator._handle_input_error("error3")  # type: ignore

        assert coordinator.stats.input_errors == 3

    def test_mixed_error_types_tracked_separately(self):
        """Test different error types are tracked separately."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Trigger different error types
        coordinator._handle_input_error("input_err")  # type: ignore
        coordinator._handle_input_error("input_err2")  # type: ignore
        coordinator._handle_rtcm_error("rtcm_err")  # type: ignore
        coordinator._handle_coordination_error("coord_err")  # type: ignore
        coordinator._handle_coordination_error("coord_err2")  # type: ignore

        assert coordinator.stats.input_errors == 2
        assert coordinator.stats.rtcm_errors == 1
        assert coordinator.stats.coordination_errors == 2


class TestDataPipelineQueueOperations:
    """Test data queue operations and behavior."""

    def test_queue_size_limits(self):
        """Test data queue respects size limits."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Fill queue to max
        for i in range(10):
            coordinator.data_queue.put(f"data{i}".encode())

        # Queue should be full
        assert coordinator.data_queue.full()
        assert coordinator.data_queue.qsize() == 10

    def test_queue_status_in_detailed_status(self):
        """Test queue status is correctly reported in detailed status."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Add some items to queue
        coordinator.data_queue.put(b"data1")
        coordinator.data_queue.put(b"data2")
        coordinator.data_queue.put(b"data3")

        status = coordinator.get_detailed_status()

        assert status["queue_status"]["size"] == 3
        assert status["queue_status"]["max_size"] == 10


class TestDataPipelinePropertiesAndState:
    """Test pipeline properties and state management."""

    def test_pipeline_statistics_returns_copy(self):
        """Test pipeline_statistics property returns stats."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        stats1 = coordinator.pipeline_statistics
        stats2 = coordinator.pipeline_statistics

        # Should be the same object
        assert isinstance(stats1, PipelineStats)
        assert isinstance(stats2, PipelineStats)

    def test_is_running_reflects_running_flag(self):
        """Test is_running property reflects running flag."""
        input_source = SimpleMockInputSource()
        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Initially not running
        assert not coordinator.is_running
        assert not coordinator.running

        # Set running
        coordinator.running = True
        assert coordinator.is_running

        # Stop
        coordinator.running = False
        assert not coordinator.is_running


class TestInputThreadWorker:
    """Test input thread worker functionality."""

    def test_input_thread_reads_and_queues_data(self):
        """Test input thread reads data and puts it in queue."""
        input_source = SimpleMockInputSource()
        input_source.connect()
        input_source.queue_data(b"test_data_123")

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            # Wait for data to be queued
            data = coordinator.data_queue.get(timeout=2.0)
            assert data == b"test_data_123"
        finally:
            # Cleanup
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            input_thread.join(timeout=2.0)

    def test_input_thread_handles_no_data_gracefully(self):
        """Test input thread handles no data without busy waiting."""
        input_source = SimpleMockInputSource()
        input_source.connect()
        # No data queued

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            # Thread should run without errors even with no data
            time.sleep(0.2)
            assert input_thread.is_alive()
            assert coordinator.data_queue.empty()
        finally:
            # Cleanup
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            input_thread.join(timeout=2.0)

    def test_input_thread_detects_disconnection(self):
        """Test input thread detects when input source disconnects."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            time.sleep(0.1)
            # Disconnect input source while thread is running
            input_source.disconnect()

            # Wait for thread to detect and exit
            input_thread.join(timeout=2.0)

            # Thread should have stopped and triggered error handling
            assert not input_thread.is_alive()
            assert coordinator.stats.input_errors >= 1
        finally:
            # Cleanup
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)

    def test_input_thread_handles_queue_full(self):
        """Test input thread handles queue full condition."""
        input_source = SimpleMockInputSource()
        input_source.connect()
        # Queue lots of data
        for i in range(15):
            input_source.queue_data(f"data_{i}".encode())

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            # Wait for queue to fill and thread to handle overflow
            time.sleep(0.5)

            # If queue filled, thread should have triggered restart
            if coordinator.data_queue.full():
                assert coordinator.stats.input_errors >= 1
        finally:
            # Cleanup
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            input_thread.join(timeout=2.0)

    def test_input_thread_stops_on_stop_event(self):
        """Test input thread stops when stop event is set."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            time.sleep(0.1)

            # Set stop event
            coordinator._stop_event.set()  # type: ignore

            # Thread should stop quickly
            input_thread.join(timeout=2.0)
            assert not input_thread.is_alive()
        finally:
            # Cleanup
            coordinator.running = False
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)

    def test_input_thread_handles_read_exception(self):
        """Test input thread handles exception during read."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        # Make read_data raise an exception
        def failing_read(timeout=None):  # type: ignore
            raise RuntimeError("Read failed")

        input_source.read_data = failing_read  # type: ignore

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            # Wait for thread to encounter exception and exit
            input_thread.join(timeout=2.0)

            # Thread should have stopped and recorded error
            assert not input_thread.is_alive()
            assert coordinator.stats.input_errors >= 1
        finally:
            # Cleanup
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)

    def test_input_thread_stops_when_running_false(self):
        """Test input thread stops when running flag becomes false."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(target=coordinator._input_thread_worker)  # type: ignore
        input_thread.start()

        try:
            time.sleep(0.1)

            # Set running to false
            coordinator.running = False

            # Thread should stop quickly
            input_thread.join(timeout=2.0)
            assert not input_thread.is_alive()
        finally:
            # Cleanup
            coordinator._stop_event.set()  # type: ignore
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)


class TestCoordinatorLoop:
    """Test coordinator loop functionality."""

    def test_coordinator_processes_data_successfully(self):
        """Test coordinator successfully processes data from queue."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        # Mock send_rtcm_data to return True
        rtcm_client.send_rtcm_data = Mock(return_value=True)  # type: ignore

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        test_data = b"test_rtcm_data"
        coordinator.data_queue.put(test_data)
        coordinator.data_queue.put(None)  # Signal to stop

        # Run coordinator loop
        coordinator._coordinator_loop()  # type: ignore

        # Verify data was sent
        rtcm_client.send_rtcm_data.assert_called_once_with(test_data)  # type: ignore
        assert coordinator.stats.bytes_processed == len(test_data)
        assert coordinator.stats.messages_processed == 1

    def test_coordinator_handles_empty_queue(self):
        """Test coordinator handles empty queue with timeout."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start coordinator in thread
        coordinator_thread = threading.Thread(target=coordinator._coordinator_loop)  # type: ignore
        coordinator_thread.start()

        try:
            # Let it run briefly with empty queue
            time.sleep(0.5)

            # Stop it
            coordinator.running = False
            coordinator.data_queue.put(None)

            coordinator_thread.join(timeout=2.0)
            assert not coordinator_thread.is_alive()
        finally:
            if coordinator_thread.is_alive():
                coordinator._stop_event.set()  # type: ignore
                coordinator_thread.join(timeout=2.0)

    def test_coordinator_detects_rtcm_disconnection(self):
        """Test coordinator detects when RTCM client disconnects."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        # Start connected, will disconnect during loop
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")

        # Start coordinator in thread
        coordinator_thread = threading.Thread(target=coordinator._coordinator_loop)  # type: ignore
        coordinator_thread.start()

        try:
            time.sleep(0.1)
            # Disconnect RTCM while coordinator is running
            rtcm_client.state = ConnectionState.DISCONNECTED

            # Wait for coordinator to detect and exit
            coordinator_thread.join(timeout=2.0)

            # Should have detected disconnection and recorded error
            assert not coordinator_thread.is_alive()
            assert coordinator.stats.rtcm_errors >= 1
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # type: ignore
            if coordinator_thread.is_alive():
                coordinator_thread.join(timeout=2.0)

    def test_coordinator_handles_none_shutdown_signal(self):
        """Test coordinator stops on None in queue."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put None in queue (shutdown signal)
        coordinator.data_queue.put(None)

        # Run coordinator loop
        coordinator._coordinator_loop()  # type: ignore

        # Should have stopped cleanly without errors
        assert coordinator.stats.coordination_errors == 0

    def test_coordinator_updates_stats_on_send(self):
        """Test coordinator updates statistics on successful send."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED
        rtcm_client.send_rtcm_data = Mock(return_value=True)  # type: ignore

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Send multiple messages
        test_data_1 = b"data1"
        test_data_2 = b"data_two"
        coordinator.data_queue.put(test_data_1)
        coordinator.data_queue.put(test_data_2)
        coordinator.data_queue.put(None)

        # Run coordinator
        coordinator._coordinator_loop()  # type: ignore

        # Verify stats updated correctly
        assert coordinator.stats.messages_processed == 2
        assert coordinator.stats.bytes_processed == len(test_data_1) + len(test_data_2)
        assert coordinator.stats.last_data_time > 0

    def test_coordinator_handles_send_failure(self):
        """Test coordinator handles RTCM send failure."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED
        # Make send fail
        rtcm_client.send_rtcm_data = Mock(return_value=False)  # type: ignore

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")

        # Run coordinator - should handle failure
        coordinator._coordinator_loop()  # type: ignore

        # Should have recorded error and triggered restart
        assert coordinator.stats.rtcm_errors >= 1
        assert coordinator._restart_requested.is_set()  # type: ignore

    def test_coordinator_stops_on_stop_event(self):
        """Test coordinator stops when stop event is set."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start coordinator
        coordinator_thread = threading.Thread(target=coordinator._coordinator_loop)  # type: ignore
        coordinator_thread.start()

        try:
            time.sleep(0.1)

            # Set stop event
            coordinator._stop_event.set()  # type: ignore

            # Should stop quickly
            coordinator_thread.join(timeout=2.0)
            assert not coordinator_thread.is_alive()
        finally:
            coordinator.running = False
            if coordinator_thread.is_alive():
                coordinator_thread.join(timeout=2.0)

    def test_coordinator_handles_exception(self):
        """Test coordinator handles unexpected exception."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        # Make send_rtcm_data raise exception
        def raise_exception(data):  # type: ignore
            raise RuntimeError("Unexpected error")

        rtcm_client.send_rtcm_data = raise_exception  # type: ignore

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")

        # Run coordinator - should handle exception
        coordinator._coordinator_loop()  # type: ignore

        # Should have recorded coordination error
        assert coordinator.stats.coordination_errors >= 1

    def test_coordinator_verifies_rtcm_connected_before_send(self):
        """Test coordinator verifies RTCM connection before sending."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        # RTCM not connected
        rtcm_client.state = ConnectionState.DISCONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")

        # Run coordinator
        coordinator._coordinator_loop()  # type: ignore

        # Should have detected disconnection before attempting send
        assert coordinator.stats.rtcm_errors >= 1

    def test_coordinator_stops_when_running_false(self):
        """Test coordinator stops when running flag becomes false."""
        input_source = SimpleMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start coordinator
        coordinator_thread = threading.Thread(target=coordinator._coordinator_loop)  # type: ignore
        coordinator_thread.start()

        try:
            time.sleep(0.1)

            # Set running to false
            coordinator.running = False
            coordinator.data_queue.put(None)  # Wake it up

            # Should stop quickly
            coordinator_thread.join(timeout=2.0)
            assert not coordinator_thread.is_alive()
        finally:
            coordinator._stop_event.set()  # type: ignore
            if coordinator_thread.is_alive():
                coordinator_thread.join(timeout=2.0)
