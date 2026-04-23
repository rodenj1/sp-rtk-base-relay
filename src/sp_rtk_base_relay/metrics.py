"""Prometheus metrics collection and export for SP-RTK-Base-Relay v2.1.

Provides per-destination labelled metrics, per-input-source metrics,
broadcast-hub lifecycle counters, and event-bus telemetry.

**Metrics surface** (namespace ``sp_rtk_base_relay``):

Per-destination (labels: ``{destination}``, sometimes also ``type``,
``filter_mode``):

* ``dest_info`` — constant 1, labels identify destination + type + filter
* ``dest_enabled`` — 1/0 reflecting ``BaseDestination.enabled``
* ``dest_running`` — 1/0 reflecting ``BaseDestination.is_running``
* ``dest_connection_status`` — 1/0 reflecting ``is_connected``
* ``dest_bytes_sent_total`` — cumulative bytes sent
* ``dest_messages_sent_total`` — cumulative messages sent
* ``dest_messages_dropped_total`` — queue overflow drops
* ``dest_messages_filtered_total`` — message-filter rejections
* ``dest_connection_attempts_total`` — cumulative connect attempts
* ``dest_successful_connections_total`` — cumulative successful connects
* ``dest_connection_failures_total`` — cumulative failed connects
* ``dest_errors_total`` — cumulative errors
* ``dest_queue_depth`` — current queue depth
* ``dest_connected_since_timestamp_seconds`` — epoch of last connect (0 if down)
* ``dest_last_send_timestamp_seconds`` — epoch of last successful send
* ``tcp_server_connected_clients`` — TCP-server-only client count

Input source (labels: ``{source_type}`` on ``input_info`` only):

* ``input_info`` — constant 1 with source type label
* ``input_connection_status`` — 1/0
* ``input_seconds_since_last_data`` — watchdog gauge (-1 if never)
* ``input_bytes_received_total`` — cumulative bytes read
* ``input_messages_received_total`` — cumulative read ops
* ``input_reconnect_attempts_total`` — cumulative reconnect attempts
* ``input_reconnect_successes_total`` — cumulative reconnect successes
* ``input_connected_since_timestamp_seconds`` — epoch of current connect

Broadcast hub:

* ``hub_running_status`` — 1/0
* ``hub_bytes_received_total`` — cumulative input bytes ingested
* ``hub_chunks_received_total`` — cumulative input chunks ingested
* ``hub_chunks_distributed_total`` — chunks fanned out
* ``hub_frames_parsed_total`` — RTCM frames parsed (filtered path only)
* ``hub_no_data_warnings_total`` — DR-7 watchdog warnings
* ``hub_registered_destinations_count`` — total registered (not just active)

(Hot add/remove activity is derived from
``rate(events_emitted_total{event_type="destination.added"}[5m])`` and the
corresponding ``destination.removed`` event type.)

Engine + EventBus (v2.1):

* ``engine_running_status`` — 1/0
* ``events_emitted_total`` — labels ``{event_type}``
* ``events_dropped_total`` — slow subscribers
* ``event_subscribers_count`` — current subscribers
* ``event_ring_buffer_depth`` — current ring buffer depth

Service:

* ``service_uptime_seconds`` — time since collector creation
* ``active_destinations_count`` — count of currently-connected destinations

Pull model: ``update_all()`` reads from ``DestinationStats``,
``BroadcastHub.stats``, ``InputSource.stats``, and ``EventBus`` on each
scrape interval (1 s in the main loop). Push model: :meth:`record_event`
is invoked by :class:`EventBus.emit()` to bump
``events_emitted_total{event_type}`` on every event — destination hot
add/remove rates are derived from this label dimension.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from prometheus_client import (
    Counter,
    Gauge,
    start_http_server,
)

if TYPE_CHECKING:
    from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
    from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
    from sp_rtk_base_relay.core.events import EventBus
    from sp_rtk_base_relay.core.input_sources.base_input import InputSource


logger = logging.getLogger(__name__)


class MetricsCollector:
    """Prometheus metrics collector for SP-RTK-Base-Relay v2.1.

    Provides per-destination, per-input-source, broadcast-hub, and
    event-bus metrics. Backward compatible with the v2.0 metric set —
    new metrics are strictly additive.

    Usage::

        mc = MetricsCollector()
        mc.start_metrics_server(port=8080)
        # Optional — wire into event bus / hub for push-model updates
        event_bus = EventBus(metrics_collector=mc)
        hub = BroadcastHub(..., metrics_collector=mc)
        # Pull-model update once per second
        mc.update_all(
            destinations=dests,
            hub=hub,
            input_source=input_src,
            event_bus=event_bus,
            engine_running=True,
        )
    """

    def __init__(self, namespace: str = "sp_rtk_base_relay") -> None:
        """Initialize metrics collector.

        Args:
            namespace: Prometheus metric name prefix.
        """
        self.namespace = namespace
        self._running = False
        self._service_start_time = time.time()

        # ── Per-destination metrics ─────────────────────────────────
        self.dest_info = Gauge(
            f"{namespace}_dest_info",
            "Destination metadata (always 1). Labels identify type and filter.",
            ["destination", "type", "filter_mode"],
        )
        self.dest_enabled = Gauge(
            f"{namespace}_dest_enabled",
            "Destination enabled flag (1=enabled, 0=disabled via stop_destination)",
            ["destination"],
        )
        self.dest_running = Gauge(
            f"{namespace}_dest_running",
            "Destination thread running (1=thread alive, 0=stopped)",
            ["destination"],
        )
        self.dest_connection_status = Gauge(
            f"{namespace}_dest_connection_status",
            "Destination connection status (1=connected, 0=disconnected)",
            ["destination"],
        )
        self.dest_bytes_sent = Counter(
            f"{namespace}_dest_bytes_sent_total",
            "Total bytes sent to destination",
            ["destination"],
        )
        self.dest_messages_sent = Counter(
            f"{namespace}_dest_messages_sent_total",
            "Total messages sent to destination",
            ["destination"],
        )
        self.dest_messages_dropped = Counter(
            f"{namespace}_dest_messages_dropped_total",
            "Total messages dropped (queue overflow) per destination",
            ["destination"],
        )
        self.dest_messages_filtered = Counter(
            f"{namespace}_dest_messages_filtered_total",
            "Total messages filtered out per destination",
            ["destination"],
        )
        self.dest_connection_attempts = Counter(
            f"{namespace}_dest_connection_attempts_total",
            "Total connection attempts per destination",
            ["destination"],
        )
        self.dest_successful_connections = Counter(
            f"{namespace}_dest_successful_connections_total",
            "Total successful connections per destination",
            ["destination"],
        )
        self.dest_connection_failures = Counter(
            f"{namespace}_dest_connection_failures_total",
            "Total connection failures per destination",
            ["destination"],
        )
        self.dest_errors = Counter(
            f"{namespace}_dest_errors_total",
            "Total errors per destination",
            ["destination"],
        )
        self.dest_queue_depth = Gauge(
            f"{namespace}_dest_queue_depth",
            "Current queue depth per destination",
            ["destination"],
        )
        self.dest_connected_since_timestamp = Gauge(
            f"{namespace}_dest_connected_since_timestamp_seconds",
            "Unix timestamp of last successful connect (0 if never/disconnected)",
            ["destination"],
        )
        self.dest_last_send_timestamp = Gauge(
            f"{namespace}_dest_last_send_timestamp_seconds",
            "Unix timestamp of last successful send (0 if never)",
            ["destination"],
        )
        self.tcp_server_connected_clients = Gauge(
            f"{namespace}_tcp_server_connected_clients",
            "Number of TCP clients connected to a tcp_server destination",
            ["destination"],
        )

        # ── Input source metrics ────────────────────────────────────
        self.input_info = Gauge(
            f"{namespace}_input_info",
            "Input source metadata (always 1). Label identifies source type.",
            ["source_type"],
        )
        self.input_connection_status = Gauge(
            f"{namespace}_input_connection_status",
            "Input source connection status (1=connected, 0=disconnected)",
        )
        self.input_seconds_since_last_data = Gauge(
            f"{namespace}_input_seconds_since_last_data",
            "Seconds since last data received from input source (DR-7)",
        )
        self.input_bytes_received = Counter(
            f"{namespace}_input_bytes_received_total",
            "Total bytes received from input source",
        )
        self.input_messages_received = Counter(
            f"{namespace}_input_messages_received_total",
            "Total read operations that returned data from input source",
        )
        self.input_reconnect_attempts = Counter(
            f"{namespace}_input_reconnect_attempts_total",
            "Total input source reconnect attempts",
        )
        self.input_reconnect_successes = Counter(
            f"{namespace}_input_reconnect_successes_total",
            "Total successful input source reconnects",
        )
        self.input_connected_since_timestamp = Gauge(
            f"{namespace}_input_connected_since_timestamp_seconds",
            "Unix timestamp of current input connection (0 if disconnected)",
        )

        # ── Broadcast hub metrics ───────────────────────────────────
        self.hub_running_status = Gauge(
            f"{namespace}_hub_running_status",
            "Broadcast hub running status (1=running, 0=stopped)",
        )
        self.hub_bytes_received = Counter(
            f"{namespace}_hub_bytes_received_total",
            "Total bytes received by broadcast hub (input ingress)",
        )
        self.hub_chunks_received = Counter(
            f"{namespace}_hub_chunks_received_total",
            "Total chunks received by broadcast hub",
        )
        self.hub_chunks_distributed = Counter(
            f"{namespace}_hub_chunks_distributed_total",
            "Total chunks distributed to destinations",
        )
        self.hub_frames_parsed = Counter(
            f"{namespace}_hub_frames_parsed_total",
            "Total RTCM frames parsed by broadcast hub (filtered path only)",
        )
        self.hub_no_data_warnings = Counter(
            f"{namespace}_hub_no_data_warnings_total",
            "Total DR-7 no-data watchdog warnings",
        )
        self.hub_registered_destinations = Gauge(
            f"{namespace}_hub_registered_destinations_count",
            "Total number of registered destinations (active or not)",
        )
        # ── Engine / Event bus metrics (v2.1) ───────────────────────
        self.engine_running_status = Gauge(
            f"{namespace}_engine_running_status",
            "RelayEngine running status (1=running, 0=stopped)",
        )
        self.events_emitted = Counter(
            f"{namespace}_events_emitted_total",
            "Total events emitted by the event bus, by event type",
            ["event_type"],
        )
        self.events_dropped = Counter(
            f"{namespace}_events_dropped_total",
            "Total events dropped due to slow/full subscriber queues",
        )
        self.event_subscribers_count = Gauge(
            f"{namespace}_event_subscribers_count",
            "Number of active event-bus subscribers",
        )
        self.event_ring_buffer_depth = Gauge(
            f"{namespace}_event_ring_buffer_depth",
            "Current depth of the event ring buffer",
        )

        # ── Service-level metrics ───────────────────────────────────
        self.service_uptime_seconds = Gauge(
            f"{namespace}_service_uptime_seconds",
            "Service uptime in seconds",
        )
        self.active_destinations_count = Gauge(
            f"{namespace}_active_destinations_count",
            "Number of currently connected destinations",
        )

        # ── Internal bookkeeping ────────────────────────────────────
        # Previous snapshot of each destination's cumulative counters
        # so we can compute deltas for Prometheus Counter.inc().
        self._prev_stats: dict[str, _DestSnapshot] = {}
        # Previous input snapshot for input counter deltas.
        self._prev_input: _InputSnapshot | None = None
        # Previous hub snapshot for hub counter deltas.
        self._prev_hub: _HubSnapshot | None = None
        # Previous event bus snapshot.
        self._prev_event_bus: _EventBusSnapshot | None = None
        # Set of destination names that have had dest_info published.
        self._dest_info_seen: set[str] = set()
        # Set of source_types that have had input_info published.
        self._input_info_seen: set[str] = set()

        logger.info("MetricsCollector v2.1 initialized")

    # ================================================================
    # Server lifecycle
    # ================================================================

    def start_metrics_server(self, port: int = 9090, host: str = "0.0.0.0") -> None:
        """Start Prometheus metrics HTTP server.

        Args:
            port: Port to listen on.
            host: Host to bind to.
        """
        if self._running:
            logger.warning("Metrics server already running")
            return

        try:
            start_http_server(port, addr=host)
            self._running = True
            logger.info(f"Metrics server started on {host}:{port}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            raise

    def stop_metrics_server(self) -> None:
        """Stop metrics server (marks as stopped)."""
        if not self._running:
            return
        self._running = False
        logger.info("Metrics server stopped")

    @property
    def is_running(self) -> bool:
        """Whether the metrics HTTP server is active."""
        return self._running

    # ================================================================
    # Push-model hooks (called synchronously from components)
    # ================================================================

    def record_event(self, event_type: str) -> None:
        """Record a single event emission by type.

        Called by :class:`EventBus.emit()` when a metrics collector is
        attached. Safe to call from any thread — ``Counter.inc()`` is
        thread-safe.

        Args:
            event_type: Dot-notation event type (e.g. ``"hub.started"``).
        """
        self.events_emitted.labels(event_type=event_type).inc()

    # ================================================================
    # Main update entry point
    # ================================================================

    def update_all(
        self,
        destinations: Sequence[BaseDestination],
        hub: BroadcastHub | None = None,
        input_connected: bool | None = None,
        input_source: InputSource | None = None,
        event_bus: EventBus | None = None,
        engine_running: bool | None = None,
    ) -> None:
        """Refresh all Prometheus metrics from live components.

        Called once per main-loop iteration (~1 s).

        Args:
            destinations: List of active destination instances.
            hub: Optional BroadcastHub (for hub-level counters + watchdog).
            input_connected: Back-compat flag for input connection state.
                Used only when ``input_source`` is not provided.
            input_source: Optional live input source (preferred — allows
                populating the full set of input metrics).
            event_bus: Optional event bus (for subscriber / ring-buffer
                / drop gauges).
            engine_running: Optional engine running state. If None, left
                untouched (useful when using the collector without the
                RelayEngine facade).
        """
        self._update_destination_metrics(destinations)
        self._update_input_metrics(input_source, input_connected)
        self._update_hub_metrics(hub, len(destinations))
        self._update_event_bus_metrics(event_bus)
        self._update_service_metrics(destinations, engine_running)

    # ================================================================
    # Per-destination update
    # ================================================================

    def _update_destination_metrics(
        self, destinations: Sequence[BaseDestination]
    ) -> None:
        """Read DestinationStats and update labelled Prometheus metrics."""
        for dest in destinations:
            stats = dest.get_stats()
            name = dest.name
            prev = self._prev_stats.get(name)

            # One-time dest_info publication
            if name not in self._dest_info_seen:
                self.dest_info.labels(
                    destination=name,
                    type=dest.destination_type,
                    filter_mode=dest.message_filter.mode.value,
                ).set(1)
                self._dest_info_seen.add(name)

            # Gauges — set absolute values every scrape
            self.dest_enabled.labels(destination=name).set(1 if dest.enabled else 0)
            self.dest_running.labels(destination=name).set(1 if dest.is_running else 0)
            self.dest_connection_status.labels(destination=name).set(
                1 if dest.is_connected else 0
            )
            self.dest_queue_depth.labels(destination=name).set(stats.queue_depth)
            self.dest_connected_since_timestamp.labels(destination=name).set(
                stats.connected_since if stats.connected_since is not None else 0.0
            )
            self.dest_last_send_timestamp.labels(destination=name).set(
                stats.last_send_time
            )

            # TCP server client count (only for tcp_server destinations)
            if dest.destination_type == "tcp_server":
                client_count = getattr(dest, "client_count", 0)
                self.tcp_server_connected_clients.labels(destination=name).set(
                    client_count
                )

            # Counters — increment by delta since last update
            if prev is not None:
                _inc_delta(
                    self.dest_bytes_sent.labels(destination=name),
                    stats.bytes_sent,
                    prev.bytes_sent,
                )
                _inc_delta(
                    self.dest_messages_sent.labels(destination=name),
                    stats.messages_sent,
                    prev.messages_sent,
                )
                _inc_delta(
                    self.dest_messages_dropped.labels(destination=name),
                    stats.messages_dropped,
                    prev.messages_dropped,
                )
                _inc_delta(
                    self.dest_messages_filtered.labels(destination=name),
                    stats.messages_filtered,
                    prev.messages_filtered,
                )
                _inc_delta(
                    self.dest_connection_attempts.labels(destination=name),
                    stats.connection_attempts,
                    prev.connection_attempts,
                )
                _inc_delta(
                    self.dest_successful_connections.labels(destination=name),
                    stats.successful_connections,
                    prev.successful_connections,
                )
                _inc_delta(
                    self.dest_connection_failures.labels(destination=name),
                    stats.connection_failures,
                    prev.connection_failures,
                )
                _inc_delta(
                    self.dest_errors.labels(destination=name),
                    stats.errors,
                    prev.errors,
                )

            # Save snapshot for next iteration
            self._prev_stats[name] = _DestSnapshot(
                bytes_sent=stats.bytes_sent,
                messages_sent=stats.messages_sent,
                messages_dropped=stats.messages_dropped,
                messages_filtered=stats.messages_filtered,
                connection_attempts=stats.connection_attempts,
                successful_connections=stats.successful_connections,
                connection_failures=stats.connection_failures,
                errors=stats.errors,
            )

    # ================================================================
    # Input source update
    # ================================================================

    def _update_input_metrics(
        self,
        input_source: InputSource | None,
        input_connected: bool | None,
    ) -> None:
        """Update input-source metrics from a live InputSource when provided.

        Falls back to the legacy ``input_connected`` flag when no
        ``input_source`` is supplied (preserves v2.0 behaviour).
        """
        if input_source is None:
            # Back-compat path — only the connection_status gauge is
            # available without a live source.
            if input_connected is not None:
                self.input_connection_status.set(1 if input_connected else 0)
            return

        source_type = input_source.source_type

        # One-time input_info publication per source type.
        if source_type not in self._input_info_seen:
            self.input_info.labels(source_type=source_type).set(1)
            self._input_info_seen.add(source_type)

        stats = input_source.stats

        # Gauges
        self.input_connection_status.set(1 if input_source.is_connected else 0)
        self.input_connected_since_timestamp.set(
            stats.connected_since if stats.connected_since is not None else 0.0
        )

        # Counters — delta-based
        prev = self._prev_input
        if prev is not None:
            _inc_delta_global(self.input_bytes_received, stats.bytes_read, prev.bytes)
            _inc_delta_global(
                self.input_messages_received, stats.messages_read, prev.messages
            )
            _inc_delta_global(
                self.input_reconnect_attempts,
                stats.connection_attempts,
                prev.attempts,
            )
            _inc_delta_global(
                self.input_reconnect_successes,
                stats.successful_connections,
                prev.successes,
            )

        self._prev_input = _InputSnapshot(
            bytes=stats.bytes_read,
            messages=stats.messages_read,
            attempts=stats.connection_attempts,
            successes=stats.successful_connections,
        )

    # ================================================================
    # Hub metrics update
    # ================================================================

    def _update_hub_metrics(
        self, hub: BroadcastHub | None, registered_count: int
    ) -> None:
        """Update hub-level metrics from live BroadcastHub."""
        if hub is None:
            # DR-7 watchdog sentinel and hub-running default
            self.input_seconds_since_last_data.set(-1)
            self.hub_running_status.set(0)
            self.hub_registered_destinations.set(registered_count)
            return

        self.hub_running_status.set(1 if hub.is_running else 0)
        self.hub_registered_destinations.set(registered_count)

        # Seconds since last data (DR-7 watchdog)
        last = hub.last_data_time
        if last > 0:
            self.input_seconds_since_last_data.set(time.time() - last)
        else:
            self.input_seconds_since_last_data.set(-1)

        # Hub counters — delta-based
        hub_stats = hub.stats
        prev = self._prev_hub
        if prev is not None:
            _inc_delta_global(
                self.hub_bytes_received, hub_stats.bytes_received, prev.bytes
            )
            _inc_delta_global(
                self.hub_chunks_received, hub_stats.chunks_received, prev.chunks_recv
            )
            _inc_delta_global(
                self.hub_chunks_distributed,
                hub_stats.chunks_distributed,
                prev.chunks_dist,
            )
            _inc_delta_global(
                self.hub_frames_parsed, hub_stats.frames_parsed, prev.frames
            )
            _inc_delta_global(
                self.hub_no_data_warnings,
                hub_stats.no_data_warnings,
                prev.no_data_warnings,
            )

        self._prev_hub = _HubSnapshot(
            bytes=hub_stats.bytes_received,
            chunks_recv=hub_stats.chunks_received,
            chunks_dist=hub_stats.chunks_distributed,
            frames=hub_stats.frames_parsed,
            no_data_warnings=hub_stats.no_data_warnings,
        )

    # ================================================================
    # Event-bus metrics update
    # ================================================================

    def _update_event_bus_metrics(self, event_bus: EventBus | None) -> None:
        """Update event-bus telemetry from a live EventBus."""
        if event_bus is None:
            return

        self.event_subscribers_count.set(event_bus.subscriber_count)
        # Ring buffer depth is private but deque iteration / len is
        # atomic under the GIL; use the public get_recent() count for
        # safety.
        self.event_ring_buffer_depth.set(len(event_bus.get_recent(count=10_000)))

        prev = self._prev_event_bus
        current_dropped = event_bus.total_events_dropped
        if prev is not None:
            _inc_delta_global(self.events_dropped, current_dropped, prev.dropped)

        self._prev_event_bus = _EventBusSnapshot(dropped=current_dropped)

    # ================================================================
    # Service-level metrics
    # ================================================================

    def _update_service_metrics(
        self,
        destinations: Sequence[BaseDestination],
        engine_running: bool | None,
    ) -> None:
        """Update service-wide metrics (uptime, active count, engine)."""
        active = sum(1 for d in destinations if d.is_connected)
        self.active_destinations_count.set(active)
        self.service_uptime_seconds.set(time.time() - self._service_start_time)

        if engine_running is not None:
            self.engine_running_status.set(1 if engine_running else 0)


# =====================================================================
# Internal helpers
# =====================================================================


class _DestSnapshot:
    """Lightweight snapshot of cumulative counters for delta computation."""

    __slots__ = (
        "bytes_sent",
        "connection_attempts",
        "connection_failures",
        "errors",
        "messages_dropped",
        "messages_filtered",
        "messages_sent",
        "successful_connections",
    )

    def __init__(
        self,
        bytes_sent: int = 0,
        messages_sent: int = 0,
        messages_dropped: int = 0,
        messages_filtered: int = 0,
        connection_attempts: int = 0,
        successful_connections: int = 0,
        connection_failures: int = 0,
        errors: int = 0,
    ) -> None:
        self.bytes_sent = bytes_sent
        self.messages_sent = messages_sent
        self.messages_dropped = messages_dropped
        self.messages_filtered = messages_filtered
        self.connection_attempts = connection_attempts
        self.successful_connections = successful_connections
        self.connection_failures = connection_failures
        self.errors = errors


class _InputSnapshot:
    """Snapshot of input-source cumulative counters."""

    __slots__ = ("attempts", "bytes", "messages", "successes")

    def __init__(
        self,
        bytes: int = 0,
        messages: int = 0,
        attempts: int = 0,
        successes: int = 0,
    ) -> None:
        self.bytes = bytes
        self.messages = messages
        self.attempts = attempts
        self.successes = successes


class _HubSnapshot:
    """Snapshot of broadcast-hub cumulative counters."""

    __slots__ = ("bytes", "chunks_dist", "chunks_recv", "frames", "no_data_warnings")

    def __init__(
        self,
        bytes: int = 0,
        chunks_recv: int = 0,
        chunks_dist: int = 0,
        frames: int = 0,
        no_data_warnings: int = 0,
    ) -> None:
        self.bytes = bytes
        self.chunks_recv = chunks_recv
        self.chunks_dist = chunks_dist
        self.frames = frames
        self.no_data_warnings = no_data_warnings


class _EventBusSnapshot:
    """Snapshot of event-bus cumulative counters."""

    __slots__ = ("dropped",)

    def __init__(self, dropped: int = 0) -> None:
        self.dropped = dropped


def _inc_delta(counter: Counter, current: int, previous: int) -> None:
    """Increment a labelled Prometheus Counter child by a positive delta.

    Args:
        counter: A labelled Counter child (result of ``.labels(...)``).
        current: Current cumulative value.
        previous: Previous cumulative value.
    """
    delta = current - previous
    if delta > 0:
        counter.inc(delta)


def _inc_delta_global(counter: Counter, current: int, previous: int) -> None:
    """Increment an unlabelled Prometheus Counter by a positive delta.

    Args:
        counter: An unlabelled Counter instance.
        current: Current cumulative value.
        previous: Previous cumulative value.
    """
    delta = current - previous
    if delta > 0:
        counter.inc(delta)
