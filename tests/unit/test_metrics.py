# pyright: reportPrivateUsage=false
"""Unit tests for MetricsCollector v2 (per-destination Prometheus metrics).

Tests the rewritten MetricsCollector that provides per-destination labelled
metrics, global input/service health metrics, and delta-based counter updates.
"""

from __future__ import annotations

import time
from unittest.mock import Mock, PropertyMock, patch

import pytest
from prometheus_client import REGISTRY

from sp_rtk_base_relay.core.destinations.base_destination import DestinationStats
from sp_rtk_base_relay.metrics import MetricsCollector, _DestSnapshot, _inc_delta

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture(autouse=True)
def clear_prometheus_registry() -> None:  # type: ignore[misc]
    """Clear Prometheus registry before and after each test."""
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass

    yield  # type: ignore[misc]

    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except Exception:
            pass


def _mock_destination(
    name: str = "test-dest",
    connected: bool = True,
    bytes_sent: int = 0,
    messages_sent: int = 0,
    messages_dropped: int = 0,
    messages_filtered: int = 0,
    connection_attempts: int = 0,
    errors: int = 0,
    queue_depth: int = 0,
) -> Mock:
    """Create a mock BaseDestination with configurable stats."""
    dest = Mock()
    dest.name = name
    dest.destination_type = "test"
    type(dest).is_connected = PropertyMock(return_value=connected)

    stats = DestinationStats(
        bytes_sent=bytes_sent,
        messages_sent=messages_sent,
        messages_dropped=messages_dropped,
        messages_filtered=messages_filtered,
        connection_attempts=connection_attempts,
        errors=errors,
        queue_depth=queue_depth,
    )
    dest.get_stats.return_value = stats
    return dest


def _mock_hub(
    running: bool = True,
    last_data_time: float = 0.0,
) -> Mock:
    """Create a mock BroadcastHub."""
    hub = Mock()
    type(hub).is_running = PropertyMock(return_value=running)
    type(hub).last_data_time = PropertyMock(return_value=last_data_time)
    return hub


# ======================================================================
# Initialization Tests
# ======================================================================


class TestMetricsInitialization:
    """Test MetricsCollector initialization."""

    def test_default_namespace(self) -> None:
        """Default namespace is 'sp_rtk_base_relay'."""
        mc = MetricsCollector()
        assert mc.namespace == "sp_rtk_base_relay"
        assert not mc.is_running
        assert mc._service_start_time > 0

    def test_custom_namespace(self) -> None:
        """Custom namespace is applied to all metrics."""
        mc = MetricsCollector(namespace="custom_ns")
        assert mc.namespace == "custom_ns"

    def test_all_per_dest_metrics_created(self) -> None:
        """All per-destination labelled metrics exist."""
        mc = MetricsCollector()
        assert mc.dest_bytes_sent is not None
        assert mc.dest_messages_sent is not None
        assert mc.dest_messages_dropped is not None
        assert mc.dest_messages_filtered is not None
        assert mc.dest_connection_status is not None
        assert mc.dest_connection_attempts is not None
        assert mc.dest_errors is not None
        assert mc.dest_queue_depth is not None

    def test_all_global_metrics_created(self) -> None:
        """All global metrics exist."""
        mc = MetricsCollector()
        assert mc.input_connection_status is not None
        assert mc.input_seconds_since_last_data is not None
        assert mc.service_uptime_seconds is not None
        assert mc.active_destinations_count is not None
        assert mc.hub_running_status is not None

    def test_prev_stats_empty_on_init(self) -> None:
        """Internal snapshot dict is empty on creation."""
        mc = MetricsCollector()
        assert mc._prev_stats == {}


# ======================================================================
# Server Lifecycle Tests
# ======================================================================


class TestMetricsServerLifecycle:
    """Test metrics HTTP server start/stop."""

    @patch("sp_rtk_base_relay.metrics.start_http_server")
    def test_start_server(self, mock_start: Mock) -> None:
        """Start server on default port."""
        mc = MetricsCollector()
        mc.start_metrics_server(port=9090, host="0.0.0.0")
        mock_start.assert_called_once_with(9090, addr="0.0.0.0")
        assert mc.is_running

    @patch("sp_rtk_base_relay.metrics.start_http_server")
    def test_start_server_custom_port(self, mock_start: Mock) -> None:
        """Start server on custom port/host."""
        mc = MetricsCollector()
        mc.start_metrics_server(port=8080, host="127.0.0.1")
        mock_start.assert_called_once_with(8080, addr="127.0.0.1")

    @patch("sp_rtk_base_relay.metrics.start_http_server")
    def test_start_server_already_running(self, mock_start: Mock) -> None:
        """Starting when already running is a no-op."""
        mc = MetricsCollector()
        mc._running = True
        mc.start_metrics_server(port=9090)
        mock_start.assert_not_called()

    @patch("sp_rtk_base_relay.metrics.start_http_server")
    def test_start_server_failure(self, mock_start: Mock) -> None:
        """Server start failure propagates exception."""
        mock_start.side_effect = OSError("Port in use")
        mc = MetricsCollector()
        with pytest.raises(OSError, match="Port in use"):
            mc.start_metrics_server(port=9090)
        assert not mc.is_running

    def test_stop_server(self) -> None:
        """Stopping marks server as not running."""
        mc = MetricsCollector()
        mc._running = True
        mc.stop_metrics_server()
        assert not mc.is_running

    def test_stop_server_not_running(self) -> None:
        """Stopping when not running is safe."""
        mc = MetricsCollector()
        mc.stop_metrics_server()
        assert not mc.is_running

    def test_is_running_property(self) -> None:
        """is_running reflects _running state."""
        mc = MetricsCollector()
        assert not mc.is_running
        mc._running = True
        assert mc.is_running


# ======================================================================
# Per-Destination Metrics Tests
# ======================================================================


class TestPerDestinationMetrics:
    """Test per-destination labelled metric updates."""

    def test_connection_status_connected(self) -> None:
        """Connected destination → gauge set to 1."""
        mc = MetricsCollector()
        dest = _mock_destination(name="surepath", connected=True)

        mc.update_all([dest])

        val = mc.dest_connection_status.labels(destination="surepath")._value.get()
        assert val == 1

    def test_connection_status_disconnected(self) -> None:
        """Disconnected destination → gauge set to 0."""
        mc = MetricsCollector()
        dest = _mock_destination(name="rtk2go", connected=False)

        mc.update_all([dest])

        val = mc.dest_connection_status.labels(destination="rtk2go")._value.get()
        assert val == 0

    def test_queue_depth_gauge(self) -> None:
        """Queue depth gauge reflects current depth."""
        mc = MetricsCollector()
        dest = _mock_destination(name="onocoy", queue_depth=42)

        mc.update_all([dest])

        val = mc.dest_queue_depth.labels(destination="onocoy")._value.get()
        assert val == 42

    def test_first_update_stores_snapshot_no_counter_increment(self) -> None:
        """First call stores snapshot but does NOT increment counters."""
        mc = MetricsCollector()
        dest = _mock_destination(name="surepath", bytes_sent=1000, messages_sent=50)

        mc.update_all([dest])

        # Snapshot stored
        assert "surepath" in mc._prev_stats
        snap = mc._prev_stats["surepath"]
        assert snap.bytes_sent == 1000
        assert snap.messages_sent == 50

        # Counter should still be 0 (no previous to compute delta against)
        val = mc.dest_bytes_sent.labels(destination="surepath")._value.get()
        assert val == 0.0

    def test_second_update_increments_counters_by_delta(self) -> None:
        """Second call increments counters by delta from first."""
        mc = MetricsCollector()

        # First update: bytes_sent=1000
        dest1 = _mock_destination(name="surepath", bytes_sent=1000, messages_sent=50)
        mc.update_all([dest1])

        # Second update: bytes_sent=1500 (delta=500)
        dest2 = _mock_destination(name="surepath", bytes_sent=1500, messages_sent=75)
        mc.update_all([dest2])

        bytes_val = mc.dest_bytes_sent.labels(destination="surepath")._value.get()
        assert bytes_val == 500.0

        msgs_val = mc.dest_messages_sent.labels(destination="surepath")._value.get()
        assert msgs_val == 25.0

    def test_multiple_updates_accumulate(self) -> None:
        """Three consecutive updates accumulate correctly."""
        mc = MetricsCollector()

        # Update 1: baseline
        mc.update_all([_mock_destination(name="d", bytes_sent=100)])
        # Update 2: +200
        mc.update_all([_mock_destination(name="d", bytes_sent=300)])
        # Update 3: +150
        mc.update_all([_mock_destination(name="d", bytes_sent=450)])

        val = mc.dest_bytes_sent.labels(destination="d")._value.get()
        assert val == 350.0  # 200 + 150

    def test_drops_counter(self) -> None:
        """Messages dropped counter increments correctly."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", messages_dropped=0)])
        mc.update_all([_mock_destination(name="d", messages_dropped=5)])

        val = mc.dest_messages_dropped.labels(destination="d")._value.get()
        assert val == 5.0

    def test_filtered_counter(self) -> None:
        """Messages filtered counter increments correctly."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", messages_filtered=0)])
        mc.update_all([_mock_destination(name="d", messages_filtered=10)])

        val = mc.dest_messages_filtered.labels(destination="d")._value.get()
        assert val == 10.0

    def test_connection_attempts_counter(self) -> None:
        """Connection attempts counter increments correctly."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", connection_attempts=1)])
        mc.update_all([_mock_destination(name="d", connection_attempts=3)])

        val = mc.dest_connection_attempts.labels(destination="d")._value.get()
        assert val == 2.0

    def test_errors_counter(self) -> None:
        """Errors counter increments correctly."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", errors=0)])
        mc.update_all([_mock_destination(name="d", errors=7)])

        val = mc.dest_errors.labels(destination="d")._value.get()
        assert val == 7.0

    def test_zero_delta_no_increment(self) -> None:
        """Zero delta (no change) → counter stays the same."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", bytes_sent=100)])
        mc.update_all([_mock_destination(name="d", bytes_sent=100)])

        val = mc.dest_bytes_sent.labels(destination="d")._value.get()
        assert val == 0.0


# ======================================================================
# Multi-Destination Isolation Tests
# ======================================================================


class TestMultiDestinationIsolation:
    """Verify metrics are isolated between destinations."""

    def test_two_destinations_independent(self) -> None:
        """Two destinations track independent counters."""
        mc = MetricsCollector()

        d1 = _mock_destination(name="surepath", bytes_sent=100)
        d2 = _mock_destination(name="rtk2go", bytes_sent=200)
        mc.update_all([d1, d2])

        d1b = _mock_destination(name="surepath", bytes_sent=300)
        d2b = _mock_destination(name="rtk2go", bytes_sent=250)
        mc.update_all([d1b, d2b])

        # surepath: 300-100=200, rtk2go: 250-200=50
        assert mc.dest_bytes_sent.labels(destination="surepath")._value.get() == 200.0
        assert mc.dest_bytes_sent.labels(destination="rtk2go")._value.get() == 50.0

    def test_three_destinations_connection_status(self) -> None:
        """Three destinations with mixed connection status."""
        mc = MetricsCollector()

        dests = [
            _mock_destination(name="surepath", connected=True),
            _mock_destination(name="rtk2go", connected=False),
            _mock_destination(name="onocoy", connected=True),
        ]
        mc.update_all(dests)

        assert (
            mc.dest_connection_status.labels(destination="surepath")._value.get() == 1
        )
        assert mc.dest_connection_status.labels(destination="rtk2go")._value.get() == 0
        assert mc.dest_connection_status.labels(destination="onocoy")._value.get() == 1

    def test_active_destinations_count(self) -> None:
        """Active destinations count reflects connected count."""
        mc = MetricsCollector()

        dests = [
            _mock_destination(name="a", connected=True),
            _mock_destination(name="b", connected=False),
            _mock_destination(name="c", connected=True),
        ]
        mc.update_all(dests)

        assert mc.active_destinations_count._value.get() == 2


# ======================================================================
# Global Metrics Tests
# ======================================================================


class TestGlobalMetrics:
    """Test global (non-per-destination) metrics."""

    def test_input_connected(self) -> None:
        """Input connection status gauge set correctly."""
        mc = MetricsCollector()
        mc.update_all([], input_connected=True)
        assert mc.input_connection_status._value.get() == 1

    def test_input_disconnected(self) -> None:
        """Input disconnected → gauge = 0."""
        mc = MetricsCollector()
        mc.update_all([], input_connected=False)
        assert mc.input_connection_status._value.get() == 0

    def test_service_uptime(self) -> None:
        """Service uptime gauge increases over time."""
        mc = MetricsCollector()
        mc._service_start_time = time.time() - 100.0

        mc.update_all([])

        uptime = mc.service_uptime_seconds._value.get()
        assert 99.0 <= uptime <= 102.0

    def test_hub_running_status_true(self) -> None:
        """Hub running → gauge = 1."""
        mc = MetricsCollector()
        hub = _mock_hub(running=True, last_data_time=time.time())

        mc.update_all([], hub=hub)

        assert mc.hub_running_status._value.get() == 1

    def test_hub_running_status_false(self) -> None:
        """Hub stopped → gauge = 0."""
        mc = MetricsCollector()
        hub = _mock_hub(running=False)

        mc.update_all([], hub=hub)

        assert mc.hub_running_status._value.get() == 0

    def test_hub_none_defaults(self) -> None:
        """No hub → hub_running=0, seconds_since_last_data=-1."""
        mc = MetricsCollector()

        mc.update_all([], hub=None)

        assert mc.hub_running_status._value.get() == 0
        assert mc.input_seconds_since_last_data._value.get() == -1

    def test_seconds_since_last_data_with_recent_data(self) -> None:
        """Recent data → small seconds_since_last_data."""
        mc = MetricsCollector()
        hub = _mock_hub(last_data_time=time.time() - 5.0)

        mc.update_all([], hub=hub)

        val = mc.input_seconds_since_last_data._value.get()
        assert 4.0 <= val <= 7.0

    def test_seconds_since_last_data_no_data_yet(self) -> None:
        """last_data_time=0 (no data yet) → -1 sentinel."""
        mc = MetricsCollector()
        hub = _mock_hub(last_data_time=0.0)

        mc.update_all([], hub=hub)

        assert mc.input_seconds_since_last_data._value.get() == -1

    def test_empty_destinations_list(self) -> None:
        """Empty destinations list → active count 0, no errors."""
        mc = MetricsCollector()

        mc.update_all([])

        assert mc.active_destinations_count._value.get() == 0


# ======================================================================
# _DestSnapshot Tests
# ======================================================================


class TestDestSnapshot:
    """Test the internal _DestSnapshot helper."""

    def test_default_values(self) -> None:
        """Defaults to all zeros."""
        snap = _DestSnapshot()
        assert snap.bytes_sent == 0
        assert snap.messages_sent == 0
        assert snap.messages_dropped == 0
        assert snap.messages_filtered == 0
        assert snap.connection_attempts == 0
        assert snap.errors == 0

    def test_custom_values(self) -> None:
        """Custom values stored correctly."""
        snap = _DestSnapshot(
            bytes_sent=1000,
            messages_sent=50,
            messages_dropped=3,
            messages_filtered=7,
            connection_attempts=2,
            errors=1,
        )
        assert snap.bytes_sent == 1000
        assert snap.messages_sent == 50
        assert snap.messages_dropped == 3
        assert snap.messages_filtered == 7
        assert snap.connection_attempts == 2
        assert snap.errors == 1


# ======================================================================
# _inc_delta Tests
# ======================================================================


class TestIncDelta:
    """Test the _inc_delta helper function."""

    def test_positive_delta(self) -> None:
        """Positive delta increments the counter."""
        mc = MetricsCollector()
        counter_child = mc.dest_bytes_sent.labels(destination="test")

        _inc_delta(counter_child, current=100, previous=60)

        assert counter_child._value.get() == 40.0

    def test_zero_delta(self) -> None:
        """Zero delta does not increment."""
        mc = MetricsCollector()
        counter_child = mc.dest_bytes_sent.labels(destination="test")

        _inc_delta(counter_child, current=100, previous=100)

        assert counter_child._value.get() == 0.0

    def test_negative_delta_ignored(self) -> None:
        """Negative delta (counter reset) is ignored."""
        mc = MetricsCollector()
        counter_child = mc.dest_bytes_sent.labels(destination="test")

        _inc_delta(counter_child, current=50, previous=100)

        assert counter_child._value.get() == 0.0


# ======================================================================
# Integration: update_all end-to-end
# ======================================================================


class TestUpdateAllEndToEnd:
    """End-to-end tests for update_all with multiple components."""

    def test_full_update_cycle(self) -> None:
        """Full update cycle: 2 destinations + hub + input."""
        mc = MetricsCollector()
        mc._service_start_time = time.time() - 60.0

        hub = _mock_hub(running=True, last_data_time=time.time() - 2.0)

        dests = [
            _mock_destination(
                name="surepath",
                connected=True,
                bytes_sent=1000,
                messages_sent=50,
            ),
            _mock_destination(
                name="rtk2go",
                connected=False,
                bytes_sent=500,
                messages_sent=25,
            ),
        ]

        # First update (stores baseline)
        mc.update_all(dests, hub=hub, input_connected=True)

        # Verify gauges
        assert (
            mc.dest_connection_status.labels(destination="surepath")._value.get() == 1
        )
        assert mc.dest_connection_status.labels(destination="rtk2go")._value.get() == 0
        assert mc.active_destinations_count._value.get() == 1
        assert mc.input_connection_status._value.get() == 1
        assert mc.hub_running_status._value.get() == 1
        assert mc.service_uptime_seconds._value.get() >= 59.0

        # Second update with new stats
        dests2 = [
            _mock_destination(
                name="surepath",
                connected=True,
                bytes_sent=2000,
                messages_sent=100,
            ),
            _mock_destination(
                name="rtk2go",
                connected=True,
                bytes_sent=800,
                messages_sent=40,
            ),
        ]
        mc.update_all(dests2, hub=hub, input_connected=True)

        # Verify counter deltas
        assert mc.dest_bytes_sent.labels(destination="surepath")._value.get() == 1000.0
        assert mc.dest_bytes_sent.labels(destination="rtk2go")._value.get() == 300.0
        assert mc.dest_messages_sent.labels(destination="surepath")._value.get() == 50.0
        assert mc.dest_messages_sent.labels(destination="rtk2go")._value.get() == 15.0
        assert mc.active_destinations_count._value.get() == 2

    def test_destination_goes_offline(self) -> None:
        """Destination disconnects → connection_status flips to 0."""
        mc = MetricsCollector()

        mc.update_all([_mock_destination(name="d", connected=True, bytes_sent=100)])
        assert mc.dest_connection_status.labels(destination="d")._value.get() == 1

        mc.update_all([_mock_destination(name="d", connected=False, bytes_sent=100)])
        assert mc.dest_connection_status.labels(destination="d")._value.get() == 0

    def test_input_goes_offline(self) -> None:
        """Input disconnects → input_connection_status flips to 0."""
        mc = MetricsCollector()

        mc.update_all([], input_connected=True)
        assert mc.input_connection_status._value.get() == 1

        mc.update_all([], input_connected=False)
        assert mc.input_connection_status._value.get() == 0
