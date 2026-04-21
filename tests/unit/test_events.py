"""Tests for the Event Bus system (v2.1 Phase 1).

Covers:
- RelayEvent creation, immutability, and string representation
- EventSubscription lifecycle, delivery, draining, iteration, context manager
- EventBus emit, subscribe, unsubscribe, ring buffer, clear
- Thread safety: concurrent emit + subscribe/unsubscribe
- Edge cases: emit with no subscribers, unsubscribe twice, closed subscription
- Event type constants verification
"""

from __future__ import annotations

import threading
import time

import pytest

from sp_rtk_base_relay.core.events import (
    DEFAULT_RING_BUFFER_SIZE,
    DEFAULT_SUBSCRIBER_QUEUE_SIZE,
    DESTINATION_ADDED,
    DESTINATION_CONNECTED,
    DESTINATION_DISCONNECTED,
    DESTINATION_ERROR,
    DESTINATION_RECONNECTED,
    DESTINATION_RECONNECTING,
    DESTINATION_REMOVED,
    DESTINATION_STARTED,
    DESTINATION_STOPPED,
    ENGINE_STARTED,
    ENGINE_STOPPED,
    HUB_STARTED,
    HUB_STOPPED,
    INPUT_CONNECTED,
    INPUT_DISCONNECTED,
    INPUT_NO_DATA_WARNING,
    INPUT_RECONNECTED,
    INPUT_RECONNECTING,
    EventBus,
    EventSubscription,
    RelayEvent,
)


# =========================================================================
# RelayEvent Tests
# =========================================================================


class TestRelayEvent:
    """Tests for the RelayEvent frozen dataclass."""

    def test_create_basic_event(self) -> None:
        """Test creating a RelayEvent with required fields."""
        event = RelayEvent(
            event_type="hub.started",
            message="Hub started",
            timestamp=1000.0,
        )
        assert event.event_type == "hub.started"
        assert event.message == "Hub started"
        assert event.timestamp == 1000.0
        assert event.payload == {}

    def test_create_event_with_payload(self) -> None:
        """Test creating a RelayEvent with payload data."""
        event = RelayEvent(
            event_type="destination.connected",
            message="Destination connected",
            timestamp=1000.0,
            payload={"destination": "rtk2go", "host": "rtk2go.com"},
        )
        assert event.payload["destination"] == "rtk2go"
        assert event.payload["host"] == "rtk2go.com"

    def test_event_is_frozen(self) -> None:
        """Test that RelayEvent is immutable (frozen dataclass)."""
        event = RelayEvent(
            event_type="hub.started",
            message="Hub started",
            timestamp=1000.0,
        )
        with pytest.raises(AttributeError):
            event.event_type = "modified"  # type: ignore[misc]

    def test_event_str_representation(self) -> None:
        """Test string representation of RelayEvent."""
        event = RelayEvent(
            event_type="hub.started",
            message="Hub started",
            timestamp=1000.0,
        )
        assert str(event) == "[hub.started] Hub started"

    def test_event_default_payload_is_empty_dict(self) -> None:
        """Test that default payload is an empty dict."""
        event = RelayEvent(
            event_type="test",
            message="test",
            timestamp=1000.0,
        )
        assert event.payload == {}
        assert isinstance(event.payload, dict)

    def test_event_payload_isolation(self) -> None:
        """Test that different events don't share the same payload dict."""
        event1 = RelayEvent(event_type="a", message="a", timestamp=1.0)
        event2 = RelayEvent(event_type="b", message="b", timestamp=2.0)
        assert event1.payload is not event2.payload

    def test_event_equality(self) -> None:
        """Test that events with same values are equal."""
        event1 = RelayEvent(
            event_type="hub.started",
            message="Hub started",
            timestamp=1000.0,
            payload={"key": "value"},
        )
        event2 = RelayEvent(
            event_type="hub.started",
            message="Hub started",
            timestamp=1000.0,
            payload={"key": "value"},
        )
        assert event1 == event2

    def test_event_inequality(self) -> None:
        """Test that events with different values are not equal."""
        event1 = RelayEvent(event_type="a", message="a", timestamp=1.0)
        event2 = RelayEvent(event_type="b", message="b", timestamp=2.0)
        assert event1 != event2


# =========================================================================
# EventSubscription Tests
# =========================================================================


class TestEventSubscription:
    """Tests for the EventSubscription class."""

    def test_subscription_initial_state(self) -> None:
        """Test subscription starts in open state with empty queue."""
        bus = EventBus()
        sub = bus.subscribe()
        assert not sub.is_closed
        assert sub.pending_count == 0
        sub.close()

    def test_deliver_event(self) -> None:
        """Test delivering an event to a subscription."""
        bus = EventBus()
        sub = bus.subscribe()
        event = RelayEvent(
            event_type="test", message="test", timestamp=time.time()
        )
        assert sub.deliver(event) is True
        assert sub.pending_count == 1
        sub.close()

    def test_deliver_to_closed_subscription(self) -> None:
        """Test delivering to a closed subscription returns False."""
        bus = EventBus()
        sub = bus.subscribe()
        sub.close()
        event = RelayEvent(
            event_type="test", message="test", timestamp=time.time()
        )
        assert sub.deliver(event) is False

    def test_deliver_to_full_queue(self) -> None:
        """Test delivering to a full queue returns False."""
        bus = EventBus(subscriber_queue_size=2)
        sub = bus.subscribe()
        event = RelayEvent(
            event_type="test", message="test", timestamp=time.time()
        )
        assert sub.deliver(event) is True
        assert sub.deliver(event) is True
        # Queue is full now
        assert sub.deliver(event) is False
        sub.close()

    def test_get_event_returns_event(self) -> None:
        """Test getting an event from the subscription."""
        bus = EventBus()
        sub = bus.subscribe()
        event = RelayEvent(
            event_type="test", message="hello", timestamp=time.time()
        )
        sub.deliver(event)
        result = sub.get_event(timeout=0.1)
        assert result is not None
        assert result.message == "hello"
        sub.close()

    def test_get_event_timeout_returns_none(self) -> None:
        """Test get_event returns None on timeout."""
        bus = EventBus()
        sub = bus.subscribe()
        result = sub.get_event(timeout=0.01)
        assert result is None
        sub.close()

    def test_get_event_on_closed_subscription(self) -> None:
        """Test get_event returns None when subscription is closed."""
        bus = EventBus()
        sub = bus.subscribe()
        sub.close()
        assert sub.get_event(timeout=0.01) is None

    def test_get_event_poison_pill_closes_subscription(self) -> None:
        """Test that receiving a poison pill closes the subscription."""
        bus = EventBus()
        sub = bus.subscribe()
        sub.send_poison_pill()
        result = sub.get_event(timeout=0.1)
        assert result is None
        assert sub.is_closed

    def test_drain_events(self) -> None:
        """Test draining all buffered events."""
        bus = EventBus()
        sub = bus.subscribe()
        for i in range(5):
            event = RelayEvent(
                event_type="test",
                message=f"event-{i}",
                timestamp=time.time(),
            )
            sub.deliver(event)

        events = sub.drain()
        assert len(events) == 5
        assert events[0].message == "event-0"
        assert events[4].message == "event-4"
        assert sub.pending_count == 0
        sub.close()

    def test_drain_empty_queue(self) -> None:
        """Test draining an empty queue returns empty list."""
        bus = EventBus()
        sub = bus.subscribe()
        events = sub.drain()
        assert events == []
        sub.close()

    def test_drain_stops_at_poison_pill(self) -> None:
        """Test drain stops when encountering a poison pill."""
        bus = EventBus()
        sub = bus.subscribe()
        event = RelayEvent(
            event_type="test", message="before", timestamp=time.time()
        )
        sub.deliver(event)
        sub.send_poison_pill()
        events = sub.drain()
        assert len(events) == 1
        assert events[0].message == "before"
        assert sub.is_closed

    def test_close_idempotent(self) -> None:
        """Test that close() can be called multiple times safely."""
        bus = EventBus()
        sub = bus.subscribe()
        sub.close()
        sub.close()  # Should not raise
        assert sub.is_closed

    def test_close_unsubscribes_from_bus(self) -> None:
        """Test that close() removes subscription from the event bus."""
        bus = EventBus()
        sub = bus.subscribe()
        assert bus.subscriber_count == 1
        sub.close()
        assert bus.subscriber_count == 0

    def test_context_manager(self) -> None:
        """Test using subscription as context manager."""
        bus = EventBus()
        with bus.subscribe() as sub:
            assert not sub.is_closed
            bus.emit("test", "hello")
            event = sub.get_event(timeout=0.1)
            assert event is not None
        assert sub.is_closed

    def test_context_manager_on_exception(self) -> None:
        """Test context manager closes subscription on exception."""
        bus = EventBus()
        sub: EventSubscription | None = None
        with pytest.raises(ValueError):
            with bus.subscribe() as s:
                sub = s
                raise ValueError("test error")
        assert sub is not None
        assert sub.is_closed

    def test_iteration_basic(self) -> None:
        """Test iterating over subscription events."""
        bus = EventBus()
        sub = bus.subscribe()

        # Deliver events then poison pill
        for i in range(3):
            sub.deliver(
                RelayEvent(
                    event_type="test",
                    message=f"msg-{i}",
                    timestamp=time.time(),
                )
            )
        sub.send_poison_pill()

        collected: list[RelayEvent] = []
        for event in sub:
            collected.append(event)

        assert len(collected) == 3
        assert collected[0].message == "msg-0"
        assert collected[2].message == "msg-2"

    def test_iteration_stops_on_closed(self) -> None:
        """Test iteration stops when subscription is closed."""
        bus = EventBus()
        sub = bus.subscribe()
        sub.close()
        collected = list(sub)
        assert collected == []

    def test_repr(self) -> None:
        """Test repr of EventSubscription."""
        bus = EventBus()
        sub = bus.subscribe()
        assert "open" in repr(sub)
        sub.close()
        assert "closed" in repr(sub)

    def test_send_poison_pill_on_full_queue(self) -> None:
        """Test send_poison_pill makes room if queue is full."""
        bus = EventBus(subscriber_queue_size=1)
        sub = bus.subscribe()
        event = RelayEvent(
            event_type="test", message="fill", timestamp=time.time()
        )
        sub.deliver(event)
        # Queue is full, poison pill should still get through
        sub.send_poison_pill()
        # The event was consumed to make room
        result = sub.get_event(timeout=0.1)
        assert result is None  # Got poison pill
        assert sub.is_closed


# =========================================================================
# EventBus Tests
# =========================================================================


class TestEventBus:
    """Tests for the EventBus class."""

    def test_create_event_bus(self) -> None:
        """Test creating an EventBus with defaults."""
        bus = EventBus()
        assert bus.subscriber_count == 0
        assert bus.total_events_emitted == 0
        assert bus.total_events_dropped == 0

    def test_create_event_bus_custom_sizes(self) -> None:
        """Test creating an EventBus with custom buffer sizes."""
        bus = EventBus(ring_buffer_size=50, subscriber_queue_size=100)
        assert bus.subscriber_count == 0

    def test_emit_basic(self) -> None:
        """Test emitting a basic event."""
        bus = EventBus()
        event = bus.emit("hub.started", "Hub started")
        assert event.event_type == "hub.started"
        assert event.message == "Hub started"
        assert event.timestamp > 0
        assert event.payload == {}
        assert bus.total_events_emitted == 1

    def test_emit_with_payload(self) -> None:
        """Test emitting an event with keyword payload."""
        bus = EventBus()
        event = bus.emit(
            "destination.connected",
            "Connected to rtk2go",
            destination="rtk2go",
            host="rtk2go.com",
        )
        assert event.payload["destination"] == "rtk2go"
        assert event.payload["host"] == "rtk2go.com"

    def test_emit_delivers_to_subscriber(self) -> None:
        """Test that emitted events are delivered to subscribers."""
        bus = EventBus()
        sub = bus.subscribe()
        bus.emit("test", "hello world")
        event = sub.get_event(timeout=0.1)
        assert event is not None
        assert event.message == "hello world"
        sub.close()

    def test_emit_delivers_to_multiple_subscribers(self) -> None:
        """Test that emitted events go to all subscribers."""
        bus = EventBus()
        sub1 = bus.subscribe()
        sub2 = bus.subscribe()
        sub3 = bus.subscribe()

        bus.emit("test", "broadcast")

        for sub in [sub1, sub2, sub3]:
            event = sub.get_event(timeout=0.1)
            assert event is not None
            assert event.message == "broadcast"
            sub.close()

    def test_emit_no_subscribers(self) -> None:
        """Test emitting with no subscribers doesn't error."""
        bus = EventBus()
        event = bus.emit("test", "nobody listening")
        assert event.event_type == "test"
        assert bus.total_events_emitted == 1
        assert bus.total_events_dropped == 0

    def test_emit_drops_on_full_queue(self) -> None:
        """Test that events are dropped when subscriber queue is full."""
        bus = EventBus(subscriber_queue_size=2)
        sub = bus.subscribe()

        bus.emit("test", "event-1")
        bus.emit("test", "event-2")
        bus.emit("test", "event-3")  # Should be dropped

        assert bus.total_events_dropped == 1
        assert sub.pending_count == 2
        sub.close()

    def test_subscribe_returns_subscription(self) -> None:
        """Test subscribe creates and returns a subscription."""
        bus = EventBus()
        sub = bus.subscribe()
        assert isinstance(sub, EventSubscription)
        assert not sub.is_closed
        assert bus.subscriber_count == 1
        sub.close()

    def test_subscribe_multiple(self) -> None:
        """Test subscribing multiple times."""
        bus = EventBus()
        subs = [bus.subscribe() for _ in range(5)]
        assert bus.subscriber_count == 5
        for sub in subs:
            sub.close()
        assert bus.subscriber_count == 0

    def test_unsubscribe_removes_subscriber(self) -> None:
        """Test unsubscribe removes the subscriber from the bus."""
        bus = EventBus()
        sub = bus.subscribe()
        assert bus.subscriber_count == 1
        result = bus.unsubscribe(sub)
        assert result is True
        assert bus.subscriber_count == 0

    def test_unsubscribe_sends_poison_pill(self) -> None:
        """Test unsubscribe sends a poison pill to the subscription."""
        bus = EventBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        # Poison pill should be in the queue
        result = sub.get_event(timeout=0.1)
        assert result is None
        assert sub.is_closed

    def test_unsubscribe_nonexistent(self) -> None:
        """Test unsubscribing a non-existent subscription returns False."""
        bus = EventBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        # Second unsubscribe should return False
        result = bus.unsubscribe(sub)
        assert result is False

    def test_unsubscribe_idempotent(self) -> None:
        """Test unsubscribe can be called multiple times safely."""
        bus = EventBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        bus.unsubscribe(sub)  # Should not raise
        assert bus.subscriber_count == 0

    # --- Ring Buffer Tests ---

    def test_ring_buffer_stores_events(self) -> None:
        """Test that events are stored in the ring buffer."""
        bus = EventBus()
        bus.emit("test", "event-1")
        bus.emit("test", "event-2")
        bus.emit("test", "event-3")

        recent = bus.get_recent(count=10)
        assert len(recent) == 3
        assert recent[0].message == "event-1"
        assert recent[2].message == "event-3"

    def test_ring_buffer_respects_maxlen(self) -> None:
        """Test that ring buffer evicts old events when full."""
        bus = EventBus(ring_buffer_size=5)
        for i in range(10):
            bus.emit("test", f"event-{i}")

        recent = bus.get_recent(count=100)
        assert len(recent) == 5
        assert recent[0].message == "event-5"
        assert recent[4].message == "event-9"

    def test_get_recent_with_count_limit(self) -> None:
        """Test get_recent respects the count parameter."""
        bus = EventBus()
        for i in range(10):
            bus.emit("test", f"event-{i}")

        recent = bus.get_recent(count=3)
        assert len(recent) == 3
        assert recent[0].message == "event-7"
        assert recent[2].message == "event-9"

    def test_get_recent_empty_buffer(self) -> None:
        """Test get_recent with no events emitted."""
        bus = EventBus()
        recent = bus.get_recent()
        assert recent == []

    def test_get_recent_fewer_events_than_requested(self) -> None:
        """Test get_recent when fewer events exist than requested."""
        bus = EventBus()
        bus.emit("test", "only-one")
        recent = bus.get_recent(count=50)
        assert len(recent) == 1
        assert recent[0].message == "only-one"

    def test_get_recent_default_count(self) -> None:
        """Test get_recent with default count of 50."""
        bus = EventBus()
        for i in range(100):
            bus.emit("test", f"event-{i}")
        recent = bus.get_recent()
        assert len(recent) == 50

    # --- Clear Tests ---

    def test_clear_removes_subscribers(self) -> None:
        """Test clear removes all subscribers."""
        bus = EventBus()
        bus.subscribe()
        bus.subscribe()
        bus.clear()
        assert bus.subscriber_count == 0

    def test_clear_sends_poison_pills(self) -> None:
        """Test clear sends poison pills to all subscribers."""
        bus = EventBus()
        sub1 = bus.subscribe()
        sub2 = bus.subscribe()
        bus.clear()
        # Both should get poison pills
        assert sub1.get_event(timeout=0.1) is None
        assert sub2.get_event(timeout=0.1) is None

    def test_clear_empties_ring_buffer(self) -> None:
        """Test clear empties the ring buffer."""
        bus = EventBus()
        bus.emit("test", "before-clear")
        bus.clear()
        assert bus.get_recent() == []

    # --- Repr Tests ---

    def test_repr(self) -> None:
        """Test repr of EventBus."""
        bus = EventBus()
        bus.subscribe()
        bus.emit("test", "hello")
        r = repr(bus)
        assert "EventBus" in r
        assert "subscribers=1" in r
        assert "emitted=1" in r

    # --- Statistics Tests ---

    def test_total_events_emitted_counter(self) -> None:
        """Test total_events_emitted increments correctly."""
        bus = EventBus()
        assert bus.total_events_emitted == 0
        bus.emit("a", "msg-a")
        bus.emit("b", "msg-b")
        bus.emit("c", "msg-c")
        assert bus.total_events_emitted == 3

    def test_total_events_dropped_counter(self) -> None:
        """Test total_events_dropped increments on full queues."""
        bus = EventBus(subscriber_queue_size=1)
        sub = bus.subscribe()
        bus.emit("test", "event-1")  # Fills queue
        bus.emit("test", "event-2")  # Dropped
        bus.emit("test", "event-3")  # Dropped
        assert bus.total_events_dropped == 2
        sub.close()


# =========================================================================
# Thread Safety Tests
# =========================================================================


class TestEventBusThreadSafety:
    """Thread safety tests for EventBus."""

    def test_concurrent_emit(self) -> None:
        """Test concurrent emit from multiple threads."""
        bus = EventBus()
        sub = bus.subscribe()
        num_threads = 5
        events_per_thread = 20

        def emitter(thread_id: int) -> None:
            for i in range(events_per_thread):
                bus.emit("test", f"t{thread_id}-e{i}", thread=thread_id)

        threads = [
            threading.Thread(target=emitter, args=(i,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert bus.total_events_emitted == num_threads * events_per_thread
        events = sub.drain()
        assert len(events) == num_threads * events_per_thread
        sub.close()

    def test_concurrent_subscribe_unsubscribe(self) -> None:
        """Test concurrent subscribe and unsubscribe."""
        bus = EventBus()
        errors: list[Exception] = []

        def subscriber_lifecycle() -> None:
            try:
                for _ in range(10):
                    sub = bus.subscribe()
                    time.sleep(0.001)
                    sub.close()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=subscriber_lifecycle)
            for _ in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent operations: {errors}"
        assert bus.subscriber_count == 0

    def test_concurrent_emit_and_subscribe(self) -> None:
        """Test emitting while subscribing/unsubscribing concurrently."""
        bus = EventBus()
        errors: list[Exception] = []
        stop_event = threading.Event()

        def emitter() -> None:
            try:
                while not stop_event.is_set():
                    bus.emit("test", "concurrent")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def subscriber() -> None:
            try:
                for _ in range(10):
                    sub = bus.subscribe()
                    time.sleep(0.002)
                    sub.close()
            except Exception as e:
                errors.append(e)

        emit_thread = threading.Thread(target=emitter)
        sub_threads = [
            threading.Thread(target=subscriber) for _ in range(3)
        ]

        emit_thread.start()
        for t in sub_threads:
            t.start()
        for t in sub_threads:
            t.join()

        stop_event.set()
        emit_thread.join()

        assert not errors, f"Errors during concurrent operations: {errors}"


# =========================================================================
# Event Type Constants Tests
# =========================================================================


class TestEventTypeConstants:
    """Tests that verify event type constants are defined correctly."""

    def test_hub_event_types(self) -> None:
        """Test hub event type constants."""
        assert HUB_STARTED == "hub.started"
        assert HUB_STOPPED == "hub.stopped"

    def test_input_event_types(self) -> None:
        """Test input event type constants."""
        assert INPUT_CONNECTED == "input.connected"
        assert INPUT_DISCONNECTED == "input.disconnected"
        assert INPUT_RECONNECTING == "input.reconnecting"
        assert INPUT_RECONNECTED == "input.reconnected"
        assert INPUT_NO_DATA_WARNING == "input.no_data_warning"

    def test_destination_event_types(self) -> None:
        """Test destination event type constants."""
        assert DESTINATION_STARTED == "destination.started"
        assert DESTINATION_STOPPED == "destination.stopped"
        assert DESTINATION_CONNECTED == "destination.connected"
        assert DESTINATION_DISCONNECTED == "destination.disconnected"
        assert DESTINATION_ERROR == "destination.error"
        assert DESTINATION_ADDED == "destination.added"
        assert DESTINATION_REMOVED == "destination.removed"
        assert DESTINATION_RECONNECTING == "destination.reconnecting"
        assert DESTINATION_RECONNECTED == "destination.reconnected"

    def test_engine_event_types(self) -> None:
        """Test engine event type constants."""
        assert ENGINE_STARTED == "engine.started"
        assert ENGINE_STOPPED == "engine.stopped"

    def test_all_event_types_use_dot_notation(self) -> None:
        """Verify all event type constants follow dot-notation pattern."""
        all_types = [
            HUB_STARTED, HUB_STOPPED,
            INPUT_CONNECTED, INPUT_DISCONNECTED, INPUT_RECONNECTING,
            INPUT_RECONNECTED, INPUT_NO_DATA_WARNING,
            DESTINATION_STARTED, DESTINATION_STOPPED,
            DESTINATION_CONNECTED, DESTINATION_DISCONNECTED,
            DESTINATION_ERROR, DESTINATION_ADDED, DESTINATION_REMOVED,
            DESTINATION_RECONNECTING, DESTINATION_RECONNECTED,
            ENGINE_STARTED, ENGINE_STOPPED,
        ]
        for event_type in all_types:
            assert "." in event_type, f"{event_type} missing dot notation"
            parts = event_type.split(".")
            assert len(parts) == 2, f"{event_type} should have exactly 2 parts"


# =========================================================================
# Default Constants Tests
# =========================================================================


class TestDefaultConstants:
    """Tests for default constant values."""

    def test_default_ring_buffer_size(self) -> None:
        """Test default ring buffer size is 200."""
        assert DEFAULT_RING_BUFFER_SIZE == 200

    def test_default_subscriber_queue_size(self) -> None:
        """Test default subscriber queue size is 500."""
        assert DEFAULT_SUBSCRIBER_QUEUE_SIZE == 500


# =========================================================================
# Integration-style Tests
# =========================================================================


class TestEventBusIntegration:
    """Integration-style tests combining EventBus, Subscription, and Events."""

    def test_full_lifecycle(self) -> None:
        """Test complete lifecycle: create bus, subscribe, emit, consume, close."""
        bus = EventBus()

        # Subscribe
        sub = bus.subscribe()
        assert bus.subscriber_count == 1

        # Emit events
        bus.emit(HUB_STARTED, "Hub started")
        bus.emit(
            DESTINATION_CONNECTED,
            "Connected to rtk2go",
            destination="rtk2go",
        )
        bus.emit(INPUT_CONNECTED, "Input source connected")

        # Consume events
        events = sub.drain()
        assert len(events) == 3
        assert events[0].event_type == HUB_STARTED
        assert events[1].event_type == DESTINATION_CONNECTED
        assert events[1].payload["destination"] == "rtk2go"
        assert events[2].event_type == INPUT_CONNECTED

        # Close
        sub.close()
        assert bus.subscriber_count == 0

    def test_late_subscriber_gets_recent(self) -> None:
        """Test that a late subscriber can see recent events via ring buffer."""
        bus = EventBus()

        # Emit events before subscribing
        bus.emit("early.event", "Event 1")
        bus.emit("early.event", "Event 2")

        # Subscribe late
        sub = bus.subscribe()

        # Late subscriber doesn't get queue events from before
        assert sub.pending_count == 0

        # But can see recent events from ring buffer
        recent = bus.get_recent()
        assert len(recent) == 2
        assert recent[0].message == "Event 1"
        assert recent[1].message == "Event 2"

        sub.close()

    def test_subscriber_isolation(self) -> None:
        """Test that slow subscriber doesn't affect fast subscriber."""
        bus = EventBus(subscriber_queue_size=2)
        fast_sub = bus.subscribe()
        slow_sub = bus.subscribe()

        # Fill slow subscriber's queue
        bus.emit("test", "event-1")
        bus.emit("test", "event-2")

        # Drain fast subscriber
        fast_events = fast_sub.drain()
        assert len(fast_events) == 2

        # Emit more — slow subscriber drops, fast subscriber receives
        bus.emit("test", "event-3")

        assert fast_sub.pending_count == 1
        # slow_sub queue was full, so event-3 was dropped for it
        assert bus.total_events_dropped == 1

        fast_sub.close()
        slow_sub.close()

    def test_emit_event_with_all_event_types(self) -> None:
        """Test emitting events with every defined event type."""
        bus = EventBus()
        sub = bus.subscribe()

        all_types = [
            HUB_STARTED, HUB_STOPPED,
            INPUT_CONNECTED, INPUT_DISCONNECTED, INPUT_RECONNECTING,
            INPUT_RECONNECTED, INPUT_NO_DATA_WARNING,
            DESTINATION_STARTED, DESTINATION_STOPPED,
            DESTINATION_CONNECTED, DESTINATION_DISCONNECTED,
            DESTINATION_ERROR, DESTINATION_ADDED, DESTINATION_REMOVED,
            DESTINATION_RECONNECTING, DESTINATION_RECONNECTED,
            ENGINE_STARTED, ENGINE_STOPPED,
        ]

        for event_type in all_types:
            bus.emit(event_type, f"Test {event_type}")

        events = sub.drain()
        assert len(events) == len(all_types)

        received_types = [e.event_type for e in events]
        assert received_types == all_types

        sub.close()

    def test_context_manager_with_emit(self) -> None:
        """Test using subscription as context manager with event emission."""
        bus = EventBus()
        collected: list[RelayEvent] = []

        with bus.subscribe() as sub:
            bus.emit("test", "inside-context")
            event = sub.get_event(timeout=0.1)
            if event:
                collected.append(event)

        assert len(collected) == 1
        assert collected[0].message == "inside-context"
        assert bus.subscriber_count == 0

    def test_ring_buffer_independent_of_subscribers(self) -> None:
        """Test ring buffer stores events regardless of subscribers."""
        bus = EventBus(ring_buffer_size=10)

        # Emit with no subscribers
        for i in range(5):
            bus.emit("test", f"no-sub-{i}")

        assert len(bus.get_recent()) == 5

        # Subscribe and emit more
        sub = bus.subscribe()
        for i in range(3):
            bus.emit("test", f"with-sub-{i}")

        # Ring buffer has all 8
        assert len(bus.get_recent(count=100)) == 8

        # Subscriber only has 3 (those emitted after subscribe)
        assert sub.pending_count == 3

        sub.close()
