"""Tests for BroadcastHub — fan-out coordinator.

Tests cover:
- Initialisation and properties
- Start / stop lifecycle
- Raw data distribution (all pass_all)
- Filtered data distribution (mixed filters)
- No-data watchdog (DR-7)
- Input source reconnection
- Disabled destination handling
- Detailed status reporting
- Frame parsing (RTCM extraction)
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import queue
import threading
import time
from typing import Any

import pytest

from sp_base_relay.core.broadcast_hub import (
    BroadcastHub,
    BroadcastStats,
)
from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.core.message_filter import FilterConfig


# ============================================================================
# Lightweight mocks (no threading in the destination — we test the hub only)
# ============================================================================


class FakeInputSource(InputSource):
    """Controllable fake input source for hub tests."""

    def __init__(self) -> None:
        super().__init__("fake")
        self.mock_connected = False
        self.data_queue: queue.Queue[bytes | None] = queue.Queue()
        self.connect_should_fail = False
        self.connect_count = 0
        self.disconnect_count = 0

    @property
    def is_connected(self) -> bool:
        return self.mock_connected

    def connect(self) -> bool:
        self.connect_count += 1
        if self.connect_should_fail:
            return False
        self.mock_connected = True
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        try:
            return self.data_queue.get(timeout=timeout or 0.1)
        except queue.Empty:
            return None

    def disconnect(self) -> None:
        self.disconnect_count += 1
        self.mock_connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}

    # --- test helpers ---
    def push(self, data: bytes) -> None:
        """Feed data that the hub's input thread will read."""
        self.data_queue.put(data)


class FakeDestination(BaseDestination):
    """Destination that records enqueued data without running a thread.

    We override start/stop to be no-ops so the hub's start/stop
    doesn't launch real destination threads.  We still use the real
    ``enqueue()`` from BaseDestination so queue overflow is tested.
    """

    def __init__(
        self,
        name: str = "fake",
        filter_config: FilterConfig | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if filter_config is None:
            filter_config = FilterConfig.pass_all()
        super().__init__(name, "fake", filter_config, queue_size)
        self.received: list[bytes] = []
        self._mock_connected = False

    # Override start/stop to be no-ops (we test the hub, not dest threads)
    def start(self) -> None:  # type: ignore[override]
        self._running = True

    def stop(self) -> None:  # type: ignore[override]
        self._running = False

    # --- ABC implementations ---
    def _connect(self) -> None:
        self._mock_connected = True

    def _disconnect(self) -> None:
        self._mock_connected = False

    def _send_data(self, data: bytes) -> None:
        pass

    def _is_connected(self) -> bool:
        return self._mock_connected

    def get_connection_info(self) -> dict[str, Any]:
        return {"name": self.name}

    # --- Override enqueue to also capture to received list ---
    def enqueue(self, data: bytes) -> bool:
        ok = super().enqueue(data)
        if ok:
            self.received.append(data)
        return ok


# ============================================================================
# Helpers
# ============================================================================

def _wait_for(predicate: Any, timeout: float = 2.0, interval: float = 0.05) -> bool:
    """Poll *predicate* until it returns True or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_hub(
    input_source: FakeInputSource | None = None,
    destinations: list[FakeDestination] | None = None,
    input_queue_size: int = 10,
) -> tuple[BroadcastHub, FakeInputSource, list[FakeDestination]]:
    """Create a hub with sensible defaults."""
    src = input_source or FakeInputSource()
    dests = destinations or [FakeDestination()]
    hub = BroadcastHub(src, dests, input_queue_size=input_queue_size)  # type: ignore[arg-type]
    return hub, src, dests


# ============================================================================
# Tests — Initialisation
# ============================================================================


class TestBroadcastHubInit:
    """BroadcastHub.__init__ tests."""

    def test_requires_at_least_one_destination(self) -> None:
        with pytest.raises(ValueError, match="at least one destination"):
            BroadcastHub(FakeInputSource(), [])

    def test_stores_destinations(self) -> None:
        hub, _, dests = _make_hub()
        assert hub.destinations == dests

    def test_destinations_is_copy(self) -> None:
        hub, _, dests = _make_hub()
        hub.destinations.append(FakeDestination(name="extra"))
        assert len(hub._destinations) == len(dests)

    def test_is_running_false_initially(self) -> None:
        hub, _, _ = _make_hub()
        assert hub.is_running is False

    def test_last_data_time_initially_zero(self) -> None:
        hub, _, _ = _make_hub()
        assert hub.last_data_time == 0.0

    def test_seconds_since_last_data_zero_when_no_data(self) -> None:
        hub, _, _ = _make_hub()
        assert hub.seconds_since_last_data == 0.0

    def test_all_pass_all_no_parsing_needed(self) -> None:
        hub, _, _ = _make_hub(destinations=[
            FakeDestination("a"),
            FakeDestination("b"),
        ])
        assert hub._any_needs_parsing is False

    def test_mixed_filters_needs_parsing(self) -> None:
        hub, _, _ = _make_hub(destinations=[
            FakeDestination("a"),
            FakeDestination("b", filter_config=FilterConfig.allowlist({1005})),
        ])
        assert hub._any_needs_parsing is True


# ============================================================================
# Tests — Lifecycle
# ============================================================================


class TestBroadcastHubLifecycle:
    """start() / stop() tests."""

    def test_start_connects_input_and_starts_destinations(self) -> None:
        hub, src, dests = _make_hub()
        hub.start()
        try:
            assert hub.is_running is True
            assert src.mock_connected is True
            assert all(d.is_running for d in dests)
        finally:
            hub.stop()

    def test_start_raises_when_input_fails(self) -> None:
        src = FakeInputSource()
        src.connect_should_fail = True
        hub, _, _ = _make_hub(input_source=src)
        with pytest.raises(ConnectionError, match="Failed to connect"):
            hub.start()

    def test_start_when_already_running_is_noop(self) -> None:
        hub, _, _ = _make_hub()
        hub.start()
        try:
            hub.start()  # should not raise
            assert hub.is_running is True
        finally:
            hub.stop()

    def test_stop_sets_running_false(self) -> None:
        hub, _, _ = _make_hub()
        hub.start()
        hub.stop()
        assert hub.is_running is False

    def test_stop_disconnects_input(self) -> None:
        hub, src, _ = _make_hub()
        hub.start()
        hub.stop()
        assert src.disconnect_count >= 1

    def test_stop_stops_destinations(self) -> None:
        hub, _, dests = _make_hub()
        hub.start()
        hub.stop()
        assert all(not d.is_running for d in dests)

    def test_stop_when_not_running_is_noop(self) -> None:
        hub, _, _ = _make_hub()
        hub.stop()  # should not raise

    def test_stats_started_at_set_on_start(self) -> None:
        hub, _, _ = _make_hub()
        hub.start()
        try:
            assert hub.stats.started_at is not None
            assert hub.stats.started_at > 0
        finally:
            hub.stop()

    def test_stats_started_at_cleared_on_stop(self) -> None:
        hub, _, _ = _make_hub()
        hub.start()
        hub.stop()
        assert hub.stats.started_at is None


# ============================================================================
# Tests — Raw distribution (all pass_all)
# ============================================================================


class TestDistributeRaw:
    """Data fan-out when all destinations use pass_all (fast path)."""

    def test_single_destination_receives_data(self) -> None:
        hub, src, dests = _make_hub()
        hub.start()
        try:
            src.push(b"hello")
            assert _wait_for(lambda: len(dests[0].received) >= 1)
            assert dests[0].received[0] == b"hello"
        finally:
            hub.stop()

    def test_multiple_destinations_all_receive_same_data(self) -> None:
        d1 = FakeDestination("d1")
        d2 = FakeDestination("d2")
        d3 = FakeDestination("d3")
        hub, src, _ = _make_hub(destinations=[d1, d2, d3])
        hub.start()
        try:
            src.push(b"chunk1")
            assert _wait_for(lambda: all(
                len(d.received) >= 1 for d in [d1, d2, d3]
            ))
            for d in [d1, d2, d3]:
                assert d.received[0] == b"chunk1"
        finally:
            hub.stop()

    def test_multiple_chunks_arrive_in_order(self) -> None:
        hub, src, dests = _make_hub()
        hub.start()
        try:
            for i in range(5):
                src.push(f"chunk{i}".encode())
            assert _wait_for(lambda: len(dests[0].received) >= 5)
            for i in range(5):
                assert dests[0].received[i] == f"chunk{i}".encode()
        finally:
            hub.stop()

    def test_stats_updated_after_distribution(self) -> None:
        hub, src, _ = _make_hub()
        hub.start()
        try:
            src.push(b"12345")
            assert _wait_for(lambda: hub.stats.chunks_distributed >= 1)
            assert hub.stats.bytes_received == 5
            assert hub.stats.chunks_received == 1
            assert hub.stats.chunks_distributed == 1
            assert hub.stats.last_data_time > 0
        finally:
            hub.stop()

    def test_disabled_destination_skipped(self) -> None:
        d1 = FakeDestination("enabled")
        d2 = FakeDestination("disabled")
        d2.enabled = False
        hub, src, _ = _make_hub(destinations=[d1, d2])
        hub.start()
        try:
            src.push(b"data")
            assert _wait_for(lambda: len(d1.received) >= 1)
            time.sleep(0.1)
            assert len(d2.received) == 0
        finally:
            hub.stop()


# ============================================================================
# Tests — Filtered distribution
# ============================================================================


class TestDistributeFiltered:
    """Data fan-out when at least one destination uses filtering."""

    def test_pass_all_dest_gets_raw_chunk(self) -> None:
        """pass_all dest gets the original raw chunk even in filtered path."""
        pass_all = FakeDestination("pass_all")
        filtered = FakeDestination(
            "filtered",
            filter_config=FilterConfig.allowlist({1005}),
        )
        hub, src, _ = _make_hub(destinations=[pass_all, filtered])
        hub.start()
        try:
            src.push(b"raw_chunk")
            assert _wait_for(lambda: len(pass_all.received) >= 1)
            assert pass_all.received[0] == b"raw_chunk"
        finally:
            hub.stop()

    def test_filtered_dest_gets_nothing_for_non_rtcm(self) -> None:
        """If no valid RTCM frames are parsed, filtered dest gets nothing."""
        filtered = FakeDestination(
            "filtered",
            filter_config=FilterConfig.blocklist({4072}),
        )
        hub, src, _ = _make_hub(destinations=[filtered])
        hub.start()
        try:
            src.push(b"not_rtcm_data")
            time.sleep(0.3)
            # Filtered dest should have nothing (no valid frames parsed)
            assert len(filtered.received) == 0
        finally:
            hub.stop()


# ============================================================================
# Tests — Frame parsing
# ============================================================================


class TestFrameParsing:
    """RTCM frame extraction from the buffer."""

    def test_parse_frames_returns_tuples(self) -> None:
        """Directly test _parse_frames with a real RTCM frame."""
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        msg = gen.generate_type_1005()
        frame_bytes = msg.to_bytes()

        hub, _, _ = _make_hub()
        frames = hub._parse_frames(frame_bytes)
        assert len(frames) == 1
        msg_id, data = frames[0]
        assert msg_id == 1005
        assert data == frame_bytes

    def test_parse_two_frames_in_one_chunk(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        f1 = gen.generate_type_1005().to_bytes()
        f2 = gen.generate_type_1077().to_bytes()

        hub, _, _ = _make_hub()
        frames = hub._parse_frames(f1 + f2)
        assert len(frames) == 2
        assert frames[0][0] == 1005
        assert frames[1][0] == 1077

    def test_incomplete_frame_kept_in_buffer(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        frame = gen.generate_type_1005().to_bytes()
        # Send only first half
        half = frame[: len(frame) // 2]

        hub, _, _ = _make_hub()
        frames = hub._parse_frames(half)
        assert len(frames) == 0
        # Buffer should hold the partial data
        assert len(hub._frame_buffer) > 0

        # Now send the rest
        rest = frame[len(frame) // 2 :]
        frames = hub._parse_frames(rest)
        assert len(frames) == 1
        assert frames[0][0] == 1005

    def test_garbage_before_frame_skipped(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        frame = gen.generate_type_1005().to_bytes()
        data = b"\x00\x01\x02\x03" + frame

        hub, _, _ = _make_hub()
        frames = hub._parse_frames(data)
        assert len(frames) == 1
        assert frames[0][0] == 1005

    def test_stats_frames_parsed_incremented(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        frame = gen.generate_type_1005().to_bytes()

        hub, _, _ = _make_hub()
        hub._parse_frames(frame)
        assert hub.stats.frames_parsed == 1


# ============================================================================
# Tests — Filtered distribution with real RTCM frames
# ============================================================================


class TestFilteredWithRealFrames:
    """End-to-end: input → parse → filter → destination queues."""

    def test_allowlist_only_passes_matching(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        f1005 = gen.generate_type_1005().to_bytes()
        f1077 = gen.generate_type_1077().to_bytes()

        # Only allow 1005
        dest = FakeDestination(
            "allow_1005",
            filter_config=FilterConfig.allowlist({1005}),
        )
        hub, src, _ = _make_hub(destinations=[dest])
        hub.start()
        try:
            src.push(f1005 + f1077)
            assert _wait_for(lambda: hub.stats.chunks_distributed >= 1)
            time.sleep(0.1)  # Let distribution finish
            # Should have only the 1005 frame
            assert len(dest.received) == 1
            assert dest.received[0] == f1005
        finally:
            hub.stop()

    def test_blocklist_drops_blocked(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        f1005 = gen.generate_type_1005().to_bytes()
        f1077 = gen.generate_type_1077().to_bytes()

        # Block 1077
        dest = FakeDestination(
            "block_1077",
            filter_config=FilterConfig.blocklist({1077}),
        )
        hub, src, _ = _make_hub(destinations=[dest])
        hub.start()
        try:
            src.push(f1005 + f1077)
            assert _wait_for(lambda: hub.stats.chunks_distributed >= 1)
            time.sleep(0.1)
            assert len(dest.received) == 1
            assert dest.received[0] == f1005
        finally:
            hub.stop()

    def test_mixed_pass_all_and_filtered(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        f1005 = gen.generate_type_1005().to_bytes()
        f1077 = gen.generate_type_1077().to_bytes()
        raw_chunk = f1005 + f1077

        pass_all_dest = FakeDestination("pa")
        filtered_dest = FakeDestination(
            "filt",
            filter_config=FilterConfig.allowlist({1005}),
        )
        hub, src, _ = _make_hub(destinations=[pass_all_dest, filtered_dest])
        hub.start()
        try:
            src.push(raw_chunk)
            assert _wait_for(lambda: hub.stats.chunks_distributed >= 1)
            time.sleep(0.1)
            # pass_all gets the raw chunk
            assert len(pass_all_dest.received) == 1
            assert pass_all_dest.received[0] == raw_chunk
            # filtered gets only 1005
            assert len(filtered_dest.received) == 1
            assert filtered_dest.received[0] == f1005
        finally:
            hub.stop()

    def test_messages_filtered_stat_updated(self) -> None:
        from tests.fixtures.rtcm_generator import RTCMGenerator

        gen = RTCMGenerator()
        f1005 = gen.generate_type_1005().to_bytes()
        f1077 = gen.generate_type_1077().to_bytes()

        dest = FakeDestination(
            "filt",
            filter_config=FilterConfig.allowlist({1005}),
        )
        hub, src, _ = _make_hub(destinations=[dest])
        hub.start()
        try:
            src.push(f1005 + f1077)
            assert _wait_for(lambda: hub.stats.chunks_distributed >= 1)
            time.sleep(0.1)
            # 1077 was filtered out → messages_filtered should be 1
            assert dest.stats.messages_filtered == 1
        finally:
            hub.stop()


# ============================================================================
# Tests — No-data watchdog (DR-7)
# ============================================================================


class TestNoDataWatchdog:
    """DR-7: passive warning when no data received."""

    def test_watchdog_fires_after_threshold(self) -> None:
        hub, _, _ = _make_hub()
        # Simulate: hub started 35 seconds ago, no data received
        hub.stats.started_at = time.time() - 35
        hub.stats.last_data_time = 0.0
        hub._check_no_data_watchdog()
        assert hub.stats.no_data_warnings == 1

    def test_watchdog_does_not_fire_before_threshold(self) -> None:
        hub, _, _ = _make_hub()
        hub.stats.started_at = time.time() - 5
        hub.stats.last_data_time = 0.0
        hub._check_no_data_watchdog()
        assert hub.stats.no_data_warnings == 0

    def test_watchdog_uses_last_data_time_when_set(self) -> None:
        hub, _, _ = _make_hub()
        hub.stats.started_at = time.time() - 120
        hub.stats.last_data_time = time.time() - 5  # Recent data
        hub._check_no_data_watchdog()
        assert hub.stats.no_data_warnings == 0

    def test_watchdog_noop_when_not_started(self) -> None:
        hub, _, _ = _make_hub()
        hub.stats.started_at = None
        hub._check_no_data_watchdog()
        assert hub.stats.no_data_warnings == 0


# ============================================================================
# Tests — Input reconnection
# ============================================================================


class TestInputReconnection:
    """Input source reconnection with backoff."""

    def test_reconnect_succeeds_on_first_attempt(self) -> None:
        hub, src, _ = _make_hub()
        src.mock_connected = False
        src.connect_should_fail = False
        hub._running = True
        hub._stop_event.clear()
        hub._reconnect_input()
        assert src.mock_connected is True
        assert hub.stats.input_reconnect_successes == 1

    def test_reconnect_tracks_attempts(self) -> None:
        src = FakeInputSource()
        src.connect_should_fail = True
        hub, _, _ = _make_hub(input_source=src)
        hub._running = True
        hub._stop_event.clear()

        # Let it try once, then stop
        def stop_after_attempt() -> None:
            time.sleep(0.3)
            hub._stop_event.set()

        t = threading.Thread(target=stop_after_attempt)
        t.start()
        hub._reconnect_input()
        t.join()
        assert hub.stats.input_reconnect_attempts >= 1

    def test_input_disconnect_triggers_reconnect_in_thread(self) -> None:
        hub, src, dests = _make_hub()
        hub.start()
        try:
            # Send some data first
            src.push(b"data1")
            assert _wait_for(lambda: len(dests[0].received) >= 1)

            # Simulate disconnect
            src.mock_connected = False
            # The input thread will detect disconnect and reconnect
            assert _wait_for(
                lambda: hub.stats.input_reconnect_attempts >= 1,
                timeout=3.0,
            )
            assert src.mock_connected is True
        finally:
            hub.stop()


# ============================================================================
# Tests — Detailed status
# ============================================================================


class TestDetailedStatus:
    """get_detailed_status() tests."""

    def test_status_structure(self) -> None:
        hub, _, _ = _make_hub()
        status = hub.get_detailed_status()
        assert "hub" in status
        assert "stats" in status
        assert "destinations" in status

    def test_status_hub_fields(self) -> None:
        hub, _, _ = _make_hub()
        hub_status = hub.get_detailed_status()["hub"]
        assert "running" in hub_status
        assert "uptime_seconds" in hub_status
        assert "input_connected" in hub_status
        assert "seconds_since_last_data" in hub_status

    def test_status_destinations_list(self) -> None:
        d1 = FakeDestination("d1")
        d2 = FakeDestination("d2")
        hub, _, _ = _make_hub(destinations=[d1, d2])
        dest_list = hub.get_detailed_status()["destinations"]
        assert len(dest_list) == 2
        assert dest_list[0]["name"] == "d1"
        assert dest_list[1]["name"] == "d2"

    def test_status_shows_running_state(self) -> None:
        hub, _, _ = _make_hub()
        assert hub.get_detailed_status()["hub"]["running"] is False
        hub.start()
        try:
            assert hub.get_detailed_status()["hub"]["running"] is True
        finally:
            hub.stop()

    def test_status_uptime_when_running(self) -> None:
        hub, _, _ = _make_hub()
        hub.start()
        try:
            time.sleep(0.1)
            uptime = hub.get_detailed_status()["hub"]["uptime_seconds"]
            assert uptime is not None
            assert uptime > 0
        finally:
            hub.stop()


# ============================================================================
# Tests — BroadcastStats dataclass
# ============================================================================


class TestBroadcastStats:
    """BroadcastStats defaults."""

    def test_defaults(self) -> None:
        s = BroadcastStats()
        assert s.bytes_received == 0
        assert s.chunks_received == 0
        assert s.frames_parsed == 0
        assert s.chunks_distributed == 0
        assert s.input_reconnect_attempts == 0
        assert s.input_reconnect_successes == 0
        assert s.last_data_time == 0.0
        assert s.started_at is None
        assert s.no_data_warnings == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
