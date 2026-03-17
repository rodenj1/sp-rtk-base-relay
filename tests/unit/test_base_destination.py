"""Tests for BaseDestination ABC and DestinationStats.

Uses a concrete MockDestination subclass to test the base class
behavior including queue management, statistics, and thread lifecycle.
"""

import threading
import time

import pytest

from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DestinationStats,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.message_filter import FilterConfig, FilterMode
from typing import Any


# ============================================================================
# Mock Destination for Testing
# ============================================================================


class MockDestination(BaseDestination):
    """Concrete destination subclass for testing base class behavior.

    All test-specific attributes are public for test access without
    triggering pylance protected-member warnings.
    """

    def __init__(
        self,
        name: str = "test_dest",
        destination_type: str = "mock",
        filter_config: FilterConfig | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if filter_config is None:
            filter_config = FilterConfig.pass_all()
        super().__init__(name, destination_type, filter_config, queue_size)
        self.mock_connected = False
        self.sent_data: list[bytes] = []
        self.connect_should_fail = False
        self.send_should_fail = False
        self.connect_count = 0
        self.disconnect_count = 0

    def _connect(self) -> None:
        self.connect_count += 1
        if self.connect_should_fail:
            raise OSError("Mock connection failed")
        self.mock_connected = True

    def _disconnect(self) -> None:
        self.disconnect_count += 1
        self.mock_connected = False

    def _send_data(self, data: bytes) -> None:
        if self.send_should_fail:
            raise OSError("Mock send failed")
        self.sent_data.append(data)

    def _is_connected(self) -> bool:
        return self.mock_connected

    def get_connection_info(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.destination_type}

    # Public test helpers to avoid accessing protected base members
    @property
    def internal_queue_maxsize(self) -> int:
        """Expose queue maxsize for testing."""
        return self._queue.maxsize

    @property
    def thread(self) -> threading.Thread | None:
        """Expose thread for testing."""
        return self._thread

    def do_attempt_connect(self) -> None:
        """Public wrapper for _attempt_connect for testing."""
        self._attempt_connect()


# ============================================================================
# DestinationStats Tests
# ============================================================================


class TestDestinationStats:
    """Tests for DestinationStats dataclass."""

    def test_default_values(self) -> None:
        """All stats start at zero/None."""
        stats = DestinationStats()
        assert stats.bytes_sent == 0
        assert stats.messages_sent == 0
        assert stats.messages_dropped == 0
        assert stats.messages_filtered == 0
        assert stats.connection_attempts == 0
        assert stats.successful_connections == 0
        assert stats.connection_failures == 0
        assert stats.errors == 0
        assert stats.last_send_time == 0.0
        assert stats.connected_since is None
        assert stats.queue_depth == 0
        assert stats.last_error is None

    def test_stats_are_mutable(self) -> None:
        """Stats fields can be updated."""
        stats = DestinationStats()
        stats.bytes_sent = 1024
        stats.messages_sent = 10
        stats.messages_dropped = 2
        assert stats.bytes_sent == 1024
        assert stats.messages_sent == 10
        assert stats.messages_dropped == 2

    def test_connected_since_optional(self) -> None:
        """connected_since can be set to a float timestamp."""
        stats = DestinationStats()
        stats.connected_since = time.time()
        assert stats.connected_since is not None
        assert stats.connected_since > 0

    def test_last_error_optional(self) -> None:
        """last_error can store error message string."""
        stats = DestinationStats()
        stats.last_error = "Connection refused"
        assert stats.last_error == "Connection refused"


# ============================================================================
# BaseDestination — Initialization Tests
# ============================================================================


class TestBaseDestinationInit:
    """Tests for BaseDestination initialization."""

    def test_cannot_instantiate_abc(self) -> None:
        """Cannot instantiate BaseDestination directly."""
        with pytest.raises(TypeError):
            BaseDestination(  # type: ignore[abstract]
                name="test",
                destination_type="test",
                filter_config=FilterConfig.pass_all(),
            )

    def test_mock_destination_init(self) -> None:
        """MockDestination initializes correctly."""
        dest = MockDestination(name="surepath", destination_type="surepath")
        assert dest.name == "surepath"
        assert dest.destination_type == "surepath"
        assert dest.enabled is True
        assert dest.is_running is False
        assert dest.queue_depth == 0

    def test_default_queue_size(self) -> None:
        """Default queue size is 100 (DR-2)."""
        assert DEFAULT_QUEUE_SIZE == 100
        dest = MockDestination()
        assert dest.internal_queue_maxsize == DEFAULT_QUEUE_SIZE

    def test_custom_queue_size(self) -> None:
        """Custom queue size is respected."""
        dest = MockDestination(queue_size=50)
        assert dest.internal_queue_maxsize == 50

    def test_filter_config_pass_all(self) -> None:
        """pass_all filter is set correctly."""
        dest = MockDestination()
        assert dest.message_filter.mode == FilterMode.PASS_ALL
        assert dest.message_filter.requires_parsing is False

    def test_filter_config_allowlist(self) -> None:
        """allowlist filter is set correctly."""
        config = FilterConfig.allowlist({1005, 1077})
        dest = MockDestination(filter_config=config)
        assert dest.message_filter.mode == FilterMode.ALLOWLIST
        assert dest.message_filter.requires_parsing is True

    def test_stats_initial_state(self) -> None:
        """Stats start at zero."""
        dest = MockDestination()
        stats = dest.get_stats()
        assert stats.bytes_sent == 0
        assert stats.messages_sent == 0
        assert stats.messages_dropped == 0


# ============================================================================
# BaseDestination — Queue Management Tests (DR-2)
# ============================================================================


class TestBaseDestinationQueue:
    """Tests for queue management per DR-2 decisions."""

    def test_enqueue_success(self) -> None:
        """Data is queued successfully."""
        dest = MockDestination()
        result = dest.enqueue(b"test_data")
        assert result is True
        assert dest.queue_depth == 1

    def test_enqueue_multiple(self) -> None:
        """Multiple items can be queued."""
        dest = MockDestination()
        for i in range(10):
            assert dest.enqueue(f"data_{i}".encode()) is True
        assert dest.queue_depth == 10

    def test_enqueue_full_drops_newest(self) -> None:
        """When queue is full, new data is dropped (DR-2: drop newest)."""
        dest = MockDestination(queue_size=3)
        assert dest.enqueue(b"data_1") is True
        assert dest.enqueue(b"data_2") is True
        assert dest.enqueue(b"data_3") is True
        # Queue is full — next enqueue should drop
        assert dest.enqueue(b"data_4") is False
        assert dest.stats.messages_dropped == 1
        assert dest.queue_depth == 3

    def test_enqueue_full_increments_drops(self) -> None:
        """Each dropped message increments the counter."""
        dest = MockDestination(queue_size=1)
        assert dest.enqueue(b"data_1") is True
        assert dest.enqueue(b"data_2") is False
        assert dest.enqueue(b"data_3") is False
        assert dest.stats.messages_dropped == 2

    def test_clear_queue_empty(self) -> None:
        """Clearing an empty queue returns 0."""
        dest = MockDestination()
        cleared = dest.clear_queue()
        assert cleared == 0

    def test_clear_queue_with_items(self) -> None:
        """Clearing a queue with items returns the count."""
        dest = MockDestination()
        dest.enqueue(b"data_1")
        dest.enqueue(b"data_2")
        dest.enqueue(b"data_3")
        cleared = dest.clear_queue()
        assert cleared == 3
        assert dest.queue_depth == 0

    def test_clear_queue_then_enqueue(self) -> None:
        """Queue can accept new data after clearing."""
        dest = MockDestination(queue_size=2)
        dest.enqueue(b"data_1")
        dest.enqueue(b"data_2")
        assert dest.enqueue(b"data_3") is False  # Full
        dest.clear_queue()
        assert dest.enqueue(b"data_3") is True  # Now has room


# ============================================================================
# BaseDestination — Statistics Tests
# ============================================================================


class TestBaseDestinationStats:
    """Tests for get_stats and statistics tracking."""

    def test_get_stats_returns_stats(self) -> None:
        """get_stats returns DestinationStats instance."""
        dest = MockDestination()
        stats = dest.get_stats()
        assert isinstance(stats, DestinationStats)

    def test_get_stats_includes_queue_depth(self) -> None:
        """get_stats updates queue_depth field."""
        dest = MockDestination()
        dest.enqueue(b"data_1")
        dest.enqueue(b"data_2")
        stats = dest.get_stats()
        assert stats.queue_depth == 2

    def test_stats_track_drops(self) -> None:
        """Stats track dropped messages."""
        dest = MockDestination(queue_size=1)
        dest.enqueue(b"data_1")
        dest.enqueue(b"data_2")  # Dropped
        stats = dest.get_stats()
        assert stats.messages_dropped == 1


# ============================================================================
# BaseDestination — Thread Lifecycle Tests
# ============================================================================


class TestBaseDestinationLifecycle:
    """Tests for start/stop thread lifecycle."""

    def test_start_sets_running(self) -> None:
        """start() sets is_running to True."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        try:
            assert dest.is_running is True
            assert dest.thread is not None
            assert dest.thread.is_alive()
        finally:
            dest.stop()

    def test_stop_sets_not_running(self) -> None:
        """stop() sets is_running to False."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        dest.stop()
        assert dest.is_running is False

    def test_stop_without_start(self) -> None:
        """stop() is safe to call without start()."""
        dest = MockDestination()
        dest.stop()  # Should not raise
        assert dest.is_running is False

    def test_double_start_is_safe(self) -> None:
        """Calling start() twice doesn't create a second thread."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        thread1 = dest.thread
        dest.start()  # Should warn and return
        thread2 = dest.thread
        try:
            assert thread1 is thread2
        finally:
            dest.stop()

    def test_thread_is_daemon(self) -> None:
        """Destination thread is a daemon thread."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        try:
            assert dest.thread is not None
            assert dest.thread.daemon is True
        finally:
            dest.stop()

    def test_thread_name(self) -> None:
        """Thread has descriptive name."""
        dest = MockDestination(name="surepath")
        dest.mock_connected = True
        dest.start()
        try:
            assert dest.thread is not None
            assert dest.thread.name == "dest-surepath"
        finally:
            dest.stop()

    def test_stop_calls_disconnect(self) -> None:
        """stop() calls _disconnect()."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        dest.stop()
        assert dest.disconnect_count >= 1

    def test_run_loop_processes_data(self) -> None:
        """Run loop reads from queue and sends data."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        try:
            dest.enqueue(b"test_data_1")
            dest.enqueue(b"test_data_2")
            # Give thread time to process
            time.sleep(0.2)
            assert len(dest.sent_data) == 2
            assert dest.sent_data[0] == b"test_data_1"
            assert dest.sent_data[1] == b"test_data_2"
            assert dest.stats.messages_sent == 2
            assert dest.stats.bytes_sent == len(b"test_data_1") + len(b"test_data_2")
        finally:
            dest.stop()

    def test_run_loop_handles_send_error(self) -> None:
        """Run loop handles send errors gracefully."""
        dest = MockDestination()
        dest.mock_connected = True
        dest.start()
        try:
            # Queue data, then make sends fail
            dest.send_should_fail = True
            dest.enqueue(b"test_data")
            time.sleep(0.2)
            assert dest.stats.errors >= 1
            assert dest.stats.last_error is not None
        finally:
            dest.stop()

    def test_run_loop_attempts_connect_when_disconnected(self) -> None:
        """Run loop calls _connect when not connected."""
        dest = MockDestination()
        dest.mock_connected = False  # Start disconnected
        dest.start()
        try:
            dest.enqueue(b"test_data")
            time.sleep(0.2)
            assert dest.connect_count >= 1
        finally:
            dest.stop()

    def test_run_loop_connection_failure_drops_data(self) -> None:
        """Data is dropped when connection attempt fails."""
        dest = MockDestination()
        dest.mock_connected = False
        dest.connect_should_fail = True
        dest.start()
        try:
            dest.enqueue(b"test_data")
            time.sleep(0.2)
            assert dest.stats.messages_dropped >= 1
            assert dest.stats.connection_failures >= 1
        finally:
            dest.stop()


# ============================================================================
# BaseDestination — Connection Stats Tests
# ============================================================================


class TestBaseDestinationConnectionStats:
    """Tests for attempt_connect stats tracking."""

    def test_attempt_connect_success(self) -> None:
        """Successful connection updates stats."""
        dest = MockDestination()
        dest.mock_connected = False
        dest.do_attempt_connect()
        assert dest.stats.connection_attempts == 1
        assert dest.stats.successful_connections == 1
        assert dest.stats.connection_failures == 0
        assert dest.stats.connected_since is not None

    def test_attempt_connect_failure(self) -> None:
        """Failed connection updates stats."""
        dest = MockDestination()
        dest.connect_should_fail = True
        dest.do_attempt_connect()
        assert dest.stats.connection_attempts == 1
        assert dest.stats.successful_connections == 0
        assert dest.stats.connection_failures == 1
        assert dest.stats.errors == 1
        assert dest.stats.last_error is not None

    def test_attempt_connect_clears_queue_on_success(self) -> None:
        """Successful reconnect clears the queue (DR-2)."""
        dest = MockDestination()
        dest.enqueue(b"stale_data_1")
        dest.enqueue(b"stale_data_2")
        assert dest.queue_depth == 2
        dest.do_attempt_connect()
        assert dest.queue_depth == 0  # Cleared per DR-2


# ============================================================================
# BaseDestination — String Representation Tests
# ============================================================================


class TestBaseDestinationRepr:
    """Tests for __str__ and __repr__."""

    def test_repr_contains_name(self) -> None:
        """repr includes destination name."""
        dest = MockDestination(name="rtk2go")
        r = repr(dest)
        assert "rtk2go" in r

    def test_repr_contains_type(self) -> None:
        """repr includes destination type."""
        dest = MockDestination(destination_type="ntrip")
        r = repr(dest)
        assert "ntrip" in r

    def test_repr_contains_filter_mode(self) -> None:
        """repr includes filter mode."""
        dest = MockDestination()
        r = repr(dest)
        assert "pass_all" in r

    def test_str_contains_status(self) -> None:
        """str shows running/stopped status."""
        dest = MockDestination(name="test")
        s = str(dest)
        assert "stopped" in s
        assert "disconnected" in s
        assert "test" in s

    def test_get_connection_info(self) -> None:
        """get_connection_info returns dict."""
        dest = MockDestination(name="surepath", destination_type="surepath")
        info = dest.get_connection_info()
        assert info["name"] == "surepath"
        assert info["type"] == "surepath"
