"""Event Bus system for real-time relay event notification.

Provides a thread-safe pub/sub event system that enables external consumers
(e.g., GPS Base Station Web UI) to observe relay state changes in real time.

Components:
    - ``RelayEvent``: Frozen dataclass representing a single event.
    - ``EventSubscription``: Per-subscriber wrapper with queue-based delivery.
    - ``EventBus``: Central hub that dispatches events to all subscribers.

Thread safety:
    - Subscriber list mutations are protected by ``threading.Lock``.
    - Event delivery uses ``put_nowait()`` to avoid blocking emitters.
    - Ring buffer uses ``collections.deque(maxlen=N)`` — atomic append under GIL.

Design decisions applied:
    - DR-10: Polling + Event Bus for status (push events for discrete changes)
    - DR-13: EventBus is owned by RelayEngine, shared with BroadcastHub/destinations
    - Q6: Thread-safe as designed, use put_nowait() to avoid blocking on slow subscribers
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

# Hub lifecycle events
HUB_STARTED = "hub.started"
HUB_STOPPED = "hub.stopped"

# Input source events
INPUT_CONNECTED = "input.connected"
INPUT_DISCONNECTED = "input.disconnected"
INPUT_RECONNECTING = "input.reconnecting"
INPUT_RECONNECTED = "input.reconnected"
INPUT_NO_DATA_WARNING = "input.no_data_warning"

# Destination lifecycle events
DESTINATION_STARTED = "destination.started"
DESTINATION_STOPPED = "destination.stopped"
DESTINATION_CONNECTED = "destination.connected"
DESTINATION_DISCONNECTED = "destination.disconnected"
DESTINATION_ERROR = "destination.error"
DESTINATION_ADDED = "destination.added"
DESTINATION_REMOVED = "destination.removed"
DESTINATION_RECONNECTING = "destination.reconnecting"
DESTINATION_RECONNECTED = "destination.reconnected"

# Engine lifecycle events
ENGINE_STARTED = "engine.started"
ENGINE_STOPPED = "engine.stopped"

# Default ring buffer size for recent event history
DEFAULT_RING_BUFFER_SIZE = 200

# Default subscriber queue size
DEFAULT_SUBSCRIBER_QUEUE_SIZE = 500


# ---------------------------------------------------------------------------
# RelayEvent — immutable event dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelayEvent:
    """An immutable event emitted by the relay system.

    Attributes:
        event_type: Dot-notation category (e.g., ``"destination.connected"``).
        message: Human-readable description of what happened.
        timestamp: ``time.time()`` epoch when the event was created.
        payload: Event-specific context (destination name, error message, etc.).
    """

    event_type: str
    message: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"[{self.event_type}] {self.message}"


# ---------------------------------------------------------------------------
# EventSubscription — per-subscriber wrapper
# ---------------------------------------------------------------------------


class EventSubscription:
    """A subscription to relay events from an :class:`EventBus`.

    Each subscriber gets its own :class:`queue.Queue` so that slow
    consumers do not block other subscribers or the emitter.

    Supports three consumption patterns:

    1. **Polling**::

           event = sub.get_event(timeout=1.0)

    2. **Blocking iteration**::

           for event in sub:
               handle(event)

    3. **Non-blocking drain**::

           events = sub.drain()

    Call :meth:`close` when done to unsubscribe and release resources.
    """

    def __init__(
        self,
        event_bus: EventBus,
        max_queue_size: int = DEFAULT_SUBSCRIBER_QUEUE_SIZE,
    ) -> None:
        """Initialize the subscription.

        Args:
            event_bus: The EventBus this subscription belongs to.
            max_queue_size: Maximum events to buffer before dropping.
        """
        self._event_bus = event_bus
        self._queue: queue.Queue[RelayEvent | None] = queue.Queue(
            maxsize=max_queue_size,
        )
        self._closed = False

    @property
    def is_closed(self) -> bool:
        """True if this subscription has been closed."""
        return self._closed

    @property
    def pending_count(self) -> int:
        """Number of events waiting to be consumed."""
        return self._queue.qsize()

    def deliver(self, event: RelayEvent) -> bool:
        """Deliver an event to this subscriber (called by EventBus).

        Note: This is part of the EventBus ↔ EventSubscription internal
        contract. External consumers should use :meth:`get_event` or
        iteration instead.

        Uses ``put_nowait()`` to avoid blocking the emitter thread.

        Args:
            event: The event to deliver.

        Returns:
            True if delivered, False if the queue was full (event dropped).
        """
        if self._closed:
            return False
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            return False

    def send_poison_pill(self) -> None:
        """Send a None sentinel to unblock any waiting get_event/iterator.

        Note: This is part of the EventBus ↔ EventSubscription internal
        contract. External consumers should use :meth:`close` instead.
        """
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # Try to make room
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(None)
            except queue.Empty:
                pass

    def get_event(self, timeout: float = 1.0) -> RelayEvent | None:
        """Get the next event, blocking up to *timeout* seconds.

        Args:
            timeout: Maximum seconds to wait. Use 0 for non-blocking.

        Returns:
            A :class:`RelayEvent`, or ``None`` if the timeout elapsed or
            the subscription was closed.
        """
        if self._closed:
            return None
        try:
            event = self._queue.get(timeout=timeout)
            if event is None:
                # Poison pill — subscription closed
                self._closed = True
                return None
            return event
        except queue.Empty:
            return None

    def drain(self) -> list[RelayEvent]:
        """Drain all currently buffered events without blocking.

        Returns:
            List of events (may be empty). Does not include poison pills.
        """
        events: list[RelayEvent] = []
        while True:
            try:
                event = self._queue.get_nowait()
                if event is None:
                    self._closed = True
                    break
                events.append(event)
            except queue.Empty:
                break
        return events

    def close(self) -> None:
        """Close this subscription and unsubscribe from the event bus.

        Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        self._event_bus.unsubscribe(self)

    def __iter__(self) -> Iterator[RelayEvent]:
        """Iterate over events until the subscription is closed."""
        return self

    def __next__(self) -> RelayEvent:
        """Get the next event (blocking).

        Raises:
            StopIteration: When the subscription is closed.
        """
        if self._closed:
            raise StopIteration
        try:
            event = self._queue.get(timeout=1.0)
        except queue.Empty:
            # Don't stop iteration on timeout — keep waiting
            raise StopIteration
        if event is None:
            self._closed = True
            raise StopIteration
        return event

    def __enter__(self) -> EventSubscription:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit — automatically closes the subscription."""
        self.close()

    def __repr__(self) -> str:
        """Detailed representation."""
        state = "closed" if self._closed else "open"
        return f"EventSubscription(state={state}, pending={self.pending_count})"


# ---------------------------------------------------------------------------
# EventBus — central event dispatcher
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe event bus for relay system events.

    Manages a list of :class:`EventSubscription` instances and dispatches
    events to all active subscribers.  Also maintains a ring buffer of
    recent events for late-joining consumers.

    Thread safety model:
        - ``_subscribers_lock`` protects the subscriber list.
        - ``emit()`` acquires the lock to snapshot subscribers, then
          delivers events outside the lock via ``put_nowait()``.
        - ``_ring_buffer`` is a ``deque(maxlen=N)`` — appends are atomic
          under the GIL, no lock needed for reads.

    Usage::

        bus = EventBus()
        sub = bus.subscribe()
        bus.emit("hub.started", "BroadcastHub started")
        event = sub.get_event(timeout=1.0)
        sub.close()
    """

    def __init__(
        self,
        ring_buffer_size: int = DEFAULT_RING_BUFFER_SIZE,
        subscriber_queue_size: int = DEFAULT_SUBSCRIBER_QUEUE_SIZE,
    ) -> None:
        """Initialize the event bus.

        Args:
            ring_buffer_size: Maximum events to keep in the ring buffer.
            subscriber_queue_size: Maximum queue size per subscriber.
        """
        self._subscribers: list[EventSubscription] = []
        self._subscribers_lock = threading.Lock()
        self._ring_buffer: deque[RelayEvent] = deque(maxlen=ring_buffer_size)
        self._subscriber_queue_size = subscriber_queue_size
        self._total_events_emitted: int = 0
        self._total_events_dropped: int = 0

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        with self._subscribers_lock:
            return len(self._subscribers)

    @property
    def total_events_emitted(self) -> int:
        """Total number of events emitted since creation."""
        return self._total_events_emitted

    @property
    def total_events_dropped(self) -> int:
        """Total number of events dropped due to full subscriber queues."""
        return self._total_events_dropped

    def emit(self, event_type: str, message: str, **payload: Any) -> RelayEvent:
        """Create and dispatch an event to all subscribers.

        This method is safe to call from any thread. It uses
        ``put_nowait()`` to deliver events, so it never blocks.

        Args:
            event_type: Dot-notation event category (e.g., ``"hub.started"``).
            message: Human-readable description.
            **payload: Additional key-value context for the event.

        Returns:
            The created :class:`RelayEvent`.
        """
        event = RelayEvent(
            event_type=event_type,
            message=message,
            timestamp=time.time(),
            payload=dict(payload) if payload else {},
        )

        # Append to ring buffer (atomic under GIL, no lock needed)
        self._ring_buffer.append(event)
        self._total_events_emitted += 1

        # Snapshot subscriber list under lock, deliver outside lock
        with self._subscribers_lock:
            subs = list(self._subscribers)

        for sub in subs:
            if not sub.deliver(event):
                self._total_events_dropped += 1

        logger.debug("Event emitted: %s", event)
        return event

    def subscribe(self) -> EventSubscription:
        """Create a new event subscription.

        The returned :class:`EventSubscription` will receive all events
        emitted after this call. Call ``.close()`` when done.

        Returns:
            A new :class:`EventSubscription`.
        """
        sub = EventSubscription(
            event_bus=self,
            max_queue_size=self._subscriber_queue_size,
        )
        with self._subscribers_lock:
            self._subscribers.append(sub)
        logger.debug(
            "New subscriber added (total: %d)",
            len(self._subscribers),
        )
        return sub

    def unsubscribe(self, subscription: EventSubscription) -> bool:
        """Remove a subscription from the event bus.

        Sends a poison pill (``None``) to unblock any waiting
        ``get_event()`` calls on the subscription.

        Safe to call multiple times for the same subscription.

        Args:
            subscription: The subscription to remove.

        Returns:
            True if the subscription was found and removed, False if
            it was already removed.
        """
        with self._subscribers_lock:
            try:
                self._subscribers.remove(subscription)
                removed = True
            except ValueError:
                removed = False

        if removed:
            subscription.send_poison_pill()
            logger.debug(
                "Subscriber removed (remaining: %d)",
                self.subscriber_count,
            )
        return removed

    def get_recent(self, count: int = 50) -> list[RelayEvent]:
        """Get recent events from the ring buffer.

        Args:
            count: Maximum number of events to return.

        Returns:
            List of recent events, oldest first. May return fewer
            than *count* if fewer events have been emitted.
        """
        # deque iteration is safe under the GIL
        all_events = list(self._ring_buffer)
        if count >= len(all_events):
            return all_events
        return all_events[-count:]

    def clear(self) -> None:
        """Clear all subscribers and the ring buffer.

        Sends poison pills to all active subscribers before clearing.
        Useful during shutdown.
        """
        with self._subscribers_lock:
            subs = list(self._subscribers)
            self._subscribers.clear()

        for sub in subs:
            sub.send_poison_pill()

        self._ring_buffer.clear()
        logger.debug("EventBus cleared")

    def __repr__(self) -> str:
        """Detailed representation."""
        return (
            f"EventBus("
            f"subscribers={self.subscriber_count}, "
            f"ring_buffer={len(self._ring_buffer)}, "
            f"emitted={self._total_events_emitted}, "
            f"dropped={self._total_events_dropped})"
        )
