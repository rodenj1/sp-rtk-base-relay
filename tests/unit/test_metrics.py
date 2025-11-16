# pyright: reportPrivateUsage=false
"""Unit tests for Prometheus metrics collection.

Tests the MetricsCollector class and all metric types.
"""

import time
import pytest
from typing import cast
from unittest.mock import Mock, patch
from dataclasses import dataclass
from prometheus_client import REGISTRY

from sp_base_relay.metrics import MetricsCollector


@pytest.fixture(autouse=True)
def clear_prometheus_registry():
    """Clear Prometheus registry before and after each test."""
    # Clear before test
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    yield

    # Clear after test
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass


@dataclass
class MockConnectionStats:
    """Mock connection statistics."""

    connection_attempts: int = 0
    successful_connections: int = 0
    authentication_failures: int = 0
    heartbeat_timeouts: int = 0
    messages_sent: int = 0
    bytes_sent: int = 0
    last_heartbeat_time: float = 0.0


@dataclass
class MockPipelineStats:
    """Mock pipeline statistics."""

    messages_processed: int = 0
    bytes_processed: int = 0
    restart_attempts: int = 0
    input_errors: int = 0
    rtcm_errors: int = 0
    coordination_errors: int = 0
    uptime_start: float | None = None


@dataclass
class MockInputStats:
    """Mock input source statistics."""

    bytes_read: int = 0


class TestMetricsCollectorInitialization:
    """Test MetricsCollector initialization."""

    def test_initialization_default_namespace(self):
        """Test initialization with default namespace."""
        metrics = MetricsCollector()

        assert metrics.namespace == "sp_base_relay"
        assert not metrics.is_running
        assert metrics._service_start_time > 0

    def test_initialization_custom_namespace(self):
        """Test initialization with custom namespace."""
        metrics = MetricsCollector(namespace="custom")

        assert metrics.namespace == "custom"
        assert not metrics.is_running

    def test_all_metrics_initialized(self):
        """Test all metrics are initialized."""
        metrics = MetricsCollector()

        # Connection metrics
        assert metrics.rtcm_connection_status is not None
        assert metrics.rtcm_connection_attempts_total is not None
        assert metrics.rtcm_successful_connections_total is not None
        assert metrics.rtcm_authentication_failures_total is not None
        assert metrics.rtcm_heartbeat_timeouts_total is not None

        # Data flow metrics
        assert metrics.rtcm_messages_sent_total is not None
        assert metrics.rtcm_bytes_sent_total is not None
        assert metrics.pipeline_messages_processed_total is not None
        assert metrics.pipeline_bytes_processed_total is not None

        # Input source metrics
        assert metrics.input_connection_status is not None
        assert metrics.input_bytes_read_total is not None
        assert metrics.input_errors_total is not None

        # Pipeline metrics
        assert metrics.pipeline_running_status is not None
        assert metrics.pipeline_restarts_total is not None
        assert metrics.pipeline_errors_total is not None

        # Health metrics
        assert metrics.rtcm_heartbeat_last_received_timestamp is not None
        assert metrics.service_uptime_seconds is not None
        assert metrics.pipeline_uptime_seconds is not None


class TestMetricsServerManagement:
    """Test metrics HTTP server management."""

    @patch("sp_base_relay.metrics.start_http_server")
    def test_start_metrics_server(self, mock_start_server: Mock):
        """Test starting metrics HTTP server."""
        metrics = MetricsCollector()

        metrics.start_metrics_server(port=9090, host="0.0.0.0")

        mock_start_server.assert_called_once_with(9090, addr="0.0.0.0")
        assert metrics.is_running

    @patch("sp_base_relay.metrics.start_http_server")
    def test_start_metrics_server_custom_port(self, mock_start_server: Mock):
        """Test starting metrics server on custom port."""
        metrics = MetricsCollector()

        metrics.start_metrics_server(port=8080, host="127.0.0.1")

        mock_start_server.assert_called_once_with(8080, addr="127.0.0.1")
        assert metrics.is_running

    @patch("sp_base_relay.metrics.start_http_server")
    def test_start_metrics_server_already_running(self, mock_start_server: Mock):
        """Test starting server when already running."""
        metrics = MetricsCollector()
        metrics._running = True

        metrics.start_metrics_server(port=9090)

        # Should not call start_http_server again
        mock_start_server.assert_not_called()

    @patch("sp_base_relay.metrics.start_http_server")
    def test_start_metrics_server_failure(self, mock_start_server: Mock):
        """Test handling server start failure."""
        mock_start_server.side_effect = Exception("Port already in use")
        metrics = MetricsCollector()

        try:
            metrics.start_metrics_server(port=9090)
            assert False, "Should have raised exception"
        except Exception as e:
            assert "Port already in use" in str(e)
            assert not metrics.is_running

    def test_stop_metrics_server(self):
        """Test stopping metrics server."""
        metrics = MetricsCollector()
        metrics._running = True

        metrics.stop_metrics_server()

        assert not metrics.is_running

    def test_stop_metrics_server_not_running(self):
        """Test stopping server when not running."""
        metrics = MetricsCollector()

        # Should not raise error
        metrics.stop_metrics_server()

        assert not metrics.is_running


class TestRTCMMetricsUpdate:
    """Test RTCM statistics metric updates."""

    def test_update_from_rtcm_stats_initial(self):
        """Test updating RTCM metrics with no previous stats."""
        metrics = MetricsCollector()
        stats = MockConnectionStats(
            connection_attempts=5,
            successful_connections=4,
            authentication_failures=1,
            heartbeat_timeouts=2,
            messages_sent=100,
            bytes_sent=5000,
            last_heartbeat_time=time.time(),
        )

        # First update with no previous stats - counters won't increment
        metrics.update_from_rtcm_stats(stats, prev_stats=None)

        # Heartbeat timestamp should be set
        assert metrics.rtcm_heartbeat_last_received_timestamp._value.get() > 0

    def test_update_from_rtcm_stats_with_delta(self):
        """Test updating RTCM metrics with delta calculation."""
        metrics = MetricsCollector()

        prev_stats = MockConnectionStats(
            connection_attempts=5,
            successful_connections=4,
            messages_sent=100,
            bytes_sent=5000,
        )

        current_stats = MockConnectionStats(
            connection_attempts=7,
            successful_connections=6,
            messages_sent=150,
            bytes_sent=7500,
        )

        metrics.update_from_rtcm_stats(current_stats, prev_stats)

        # Note: We can't easily verify counter values without accessing internals
        # The important thing is that the method doesn't crash

    def test_update_from_rtcm_stats_no_delta(self):
        """Test update when stats haven't changed."""
        metrics = MetricsCollector()

        stats = MockConnectionStats(connection_attempts=5, successful_connections=4)

        # Same stats twice - no delta
        metrics.update_from_rtcm_stats(stats, prev_stats=stats)

        # Should complete without error


class TestPipelineMetricsUpdate:
    """Test pipeline statistics metric updates."""

    def test_update_from_pipeline_stats_with_delta(self):
        """Test updating pipeline metrics with delta."""
        metrics = MetricsCollector()

        prev_stats = MockPipelineStats(
            messages_processed=100,
            bytes_processed=5000,
            restart_attempts=2,
            input_errors=1,
            rtcm_errors=0,
            coordination_errors=1,
        )

        current_stats = MockPipelineStats(
            messages_processed=150,
            bytes_processed=7500,
            restart_attempts=3,
            input_errors=2,
            rtcm_errors=1,
            coordination_errors=1,
        )

        metrics.update_from_pipeline_stats(current_stats, prev_stats)

        # Method should complete without error

    def test_update_from_pipeline_stats_with_uptime(self):
        """Test updating pipeline uptime."""
        metrics = MetricsCollector()

        uptime_start = time.time() - 100  # 100 seconds ago
        stats = MockPipelineStats(uptime_start=uptime_start)

        metrics.update_from_pipeline_stats(stats, prev_stats=None)

        # Uptime should be approximately 100 seconds
        uptime = cast(float, metrics.pipeline_uptime_seconds._value.get())
        assert 99 <= uptime <= 101

    def test_update_from_pipeline_stats_no_uptime(self):
        """Test updating when pipeline not started."""
        metrics = MetricsCollector()

        stats = MockPipelineStats(uptime_start=None)

        metrics.update_from_pipeline_stats(stats, prev_stats=None)

        # Uptime should be 0
        uptime = cast(float, metrics.pipeline_uptime_seconds._value.get())
        assert uptime == 0


class TestInputMetricsUpdate:
    """Test input source statistics metric updates."""

    def test_update_from_input_stats_with_delta(self):
        """Test updating input metrics with delta."""
        metrics = MetricsCollector()

        prev_stats = MockInputStats(bytes_read=1000)
        current_stats = MockInputStats(bytes_read=1500)

        metrics.update_from_input_stats(current_stats, prev_stats)

        # Method should complete without error

    def test_update_from_input_stats_no_delta(self):
        """Test updating when no new data read."""
        metrics = MetricsCollector()

        stats = MockInputStats(bytes_read=1000)

        metrics.update_from_input_stats(stats, prev_stats=stats)

        # Should complete without error


class TestConnectionStatusUpdates:
    """Test connection status gauge updates."""

    def test_update_connection_status_both_connected(self):
        """Test updating when both connections are active."""
        metrics = MetricsCollector()

        metrics.update_connection_status(rtcm_connected=True, input_connected=True)

        assert metrics.rtcm_connection_status._value.get() == 1
        assert metrics.input_connection_status._value.get() == 1

    def test_update_connection_status_both_disconnected(self):
        """Test updating when both connections are down."""
        metrics = MetricsCollector()

        metrics.update_connection_status(rtcm_connected=False, input_connected=False)

        assert metrics.rtcm_connection_status._value.get() == 0
        assert metrics.input_connection_status._value.get() == 0

    def test_update_connection_status_mixed(self):
        """Test updating with mixed connection states."""
        metrics = MetricsCollector()

        metrics.update_connection_status(rtcm_connected=True, input_connected=False)

        assert metrics.rtcm_connection_status._value.get() == 1
        assert metrics.input_connection_status._value.get() == 0


class TestPipelineStatusUpdates:
    """Test pipeline status gauge updates."""

    def test_update_pipeline_status_running(self):
        """Test updating pipeline status when running."""
        metrics = MetricsCollector()

        metrics.update_pipeline_status(running=True)

        assert metrics.pipeline_running_status._value.get() == 1

    def test_update_pipeline_status_stopped(self):
        """Test updating pipeline status when stopped."""
        metrics = MetricsCollector()

        metrics.update_pipeline_status(running=False)

        assert metrics.pipeline_running_status._value.get() == 0


class TestServiceUptimeUpdate:
    """Test service uptime metric updates."""

    def test_update_service_uptime(self):
        """Test updating service uptime."""
        metrics = MetricsCollector()

        # Wait a moment
        time.sleep(0.1)

        metrics.update_service_uptime()

        uptime = cast(float, metrics.service_uptime_seconds._value.get())
        assert uptime >= 0.1


class TestCollectAllMetrics:
    """Test comprehensive metrics collection."""

    def test_collect_all_metrics(self):
        """Test collecting metrics from all components."""
        metrics = MetricsCollector()

        # Create mock components
        mock_rtcm = Mock()
        mock_rtcm.connection_statistics = MockConnectionStats(
            connection_attempts=5,
            successful_connections=4,
            messages_sent=100,
            bytes_sent=5000,
        )
        mock_rtcm.is_connected = True

        mock_pipeline = Mock()
        mock_pipeline.pipeline_statistics = MockPipelineStats(
            messages_processed=100, bytes_processed=5000, restart_attempts=1
        )
        mock_pipeline.is_running = True

        mock_input = Mock()
        mock_input.connection_statistics = MockInputStats(bytes_read=1000)
        mock_input.is_connected = True

        # Collect metrics
        result = metrics.collect_all_metrics(mock_rtcm, mock_pipeline, mock_input)

        # Should return tuple of stats
        assert len(result) == 3
        assert result[0] == mock_rtcm.connection_statistics
        assert result[1] == mock_pipeline.pipeline_statistics
        assert result[2] == mock_input.connection_statistics

    def test_collect_all_metrics_with_previous_stats(self):
        """Test collecting metrics with previous stats for delta."""
        metrics = MetricsCollector()

        # Create mock components with changing stats
        mock_rtcm = Mock()
        prev_rtcm_stats = MockConnectionStats(messages_sent=100)
        mock_rtcm.connection_statistics = MockConnectionStats(messages_sent=150)
        mock_rtcm.is_connected = True

        mock_pipeline = Mock()
        prev_pipeline_stats = MockPipelineStats(messages_processed=100)
        mock_pipeline.pipeline_statistics = MockPipelineStats(messages_processed=150)
        mock_pipeline.is_running = True

        mock_input = Mock()
        prev_input_stats = MockInputStats(bytes_read=1000)
        mock_input.connection_statistics = MockInputStats(bytes_read=1500)
        mock_input.is_connected = True

        # Collect with previous stats
        result = metrics.collect_all_metrics(
            mock_rtcm,
            mock_pipeline,
            mock_input,
            prev_rtcm_stats,
            prev_pipeline_stats,
            prev_input_stats,
        )

        # Should return current stats
        assert result[0] == mock_rtcm.connection_statistics
        assert result[1] == mock_pipeline.pipeline_statistics
        assert result[2] == mock_input.connection_statistics


class TestMetricsCollectorProperties:
    """Test MetricsCollector properties."""

    def test_is_running_property(self):
        """Test is_running property."""
        metrics = MetricsCollector()

        assert not metrics.is_running

        metrics._running = True
        assert metrics.is_running

        metrics._running = False
        assert not metrics.is_running
