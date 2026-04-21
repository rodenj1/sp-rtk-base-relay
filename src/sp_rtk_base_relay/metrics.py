"""Prometheus metrics collection and export for SP-Base-Relay v2.

Clean-slate rewrite for the multi-destination architecture.
All metrics are per-destination using Prometheus labels, replacing
the single-destination global counters from v1.

Pull model: ``update_all()`` reads from ``DestinationStats`` and
``BroadcastHub`` on each scrape interval (1 s in the main loop).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
import time
from typing import TYPE_CHECKING

from prometheus_client import (
    Counter,
    Gauge,
    start_http_server,
)

if TYPE_CHECKING:
    from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
    from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination


logger = logging.getLogger(__name__)


class MetricsCollector:
    """Prometheus metrics collector for SP-Base-Relay v2.

    Provides **per-destination** metrics (labeled by ``destination``)
    and **global** metrics for the input source and service health.

    Usage::

        mc = MetricsCollector()
        mc.start_metrics_server(port=8080)
        # ... every 1 s in the main loop ...
        mc.update_all(destinations, hub, input_connected=True)
    """

    def __init__(self, namespace: str = "sp_rtk_base_relay") -> None:
        """Initialize metrics collector.

        Args:
            namespace: Prometheus metric name prefix.
        """
        self.namespace = namespace
        self._running = False
        self._service_start_time = time.time()

        # ── Per-destination metrics (labelled) ──────────────────────
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
        self.dest_connection_status = Gauge(
            f"{namespace}_dest_connection_status",
            "Destination connection status (1=connected, 0=disconnected)",
            ["destination"],
        )
        self.dest_connection_attempts = Counter(
            f"{namespace}_dest_connection_attempts_total",
            "Total connection attempts per destination",
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
        self.tcp_server_connected_clients = Gauge(
            f"{namespace}_tcp_server_connected_clients",
            "Number of TCP clients connected to a tcp_server destination",
            ["destination"],
        )

        # ── Global metrics ──────────────────────────────────────────
        self.input_connection_status = Gauge(
            f"{namespace}_input_connection_status",
            "Input source connection status (1=connected, 0=disconnected)",
        )
        self.input_seconds_since_last_data = Gauge(
            f"{namespace}_input_seconds_since_last_data",
            "Seconds since last data received from input source (DR-7)",
        )
        self.service_uptime_seconds = Gauge(
            f"{namespace}_service_uptime_seconds",
            "Service uptime in seconds",
        )
        self.active_destinations_count = Gauge(
            f"{namespace}_active_destinations_count",
            "Number of currently connected destinations",
        )
        self.hub_running_status = Gauge(
            f"{namespace}_hub_running_status",
            "Broadcast hub running status (1=running, 0=stopped)",
        )

        # ── Internal bookkeeping ────────────────────────────────────
        # Previous snapshot of each destination's cumulative counters
        # so we can compute deltas for Prometheus Counter.inc().
        self._prev_stats: dict[str, _DestSnapshot] = {}

        logger.info("MetricsCollector v2 initialized")

    # ================================================================
    # Server lifecycle
    # ================================================================

    def start_metrics_server(
        self, port: int = 9090, host: str = "0.0.0.0"
    ) -> None:
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
    # Main update entry point
    # ================================================================

    def update_all(
        self,
        destinations: Sequence[BaseDestination],
        hub: BroadcastHub | None = None,
        input_connected: bool = False,
    ) -> None:
        """Refresh all Prometheus metrics from live components.

        Called once per main-loop iteration (~1 s).

        Args:
            destinations: List of active destination instances.
            hub: BroadcastHub (for input health data).
            input_connected: Whether the GPS input source is connected.
        """
        self._update_destination_metrics(destinations)
        self._update_global_metrics(destinations, hub, input_connected)

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

            # Gauges — set absolute values
            self.dest_connection_status.labels(destination=name).set(
                1 if dest.is_connected else 0
            )
            self.dest_queue_depth.labels(destination=name).set(
                stats.queue_depth
            )

            # TCP server client count (only for tcp_server destinations)
            if dest.destination_type == "tcp_server":
                client_count = getattr(dest, "client_count", 0)
                self.tcp_server_connected_clients.labels(
                    destination=name
                ).set(client_count)

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
                errors=stats.errors,
            )

    # ================================================================
    # Global metrics update
    # ================================================================

    def _update_global_metrics(
        self,
        destinations: Sequence[BaseDestination],
        hub: BroadcastHub | None,
        input_connected: bool,
    ) -> None:
        """Update global (non-per-destination) metrics."""
        # Input health
        self.input_connection_status.set(1 if input_connected else 0)

        # Seconds since last data (DR-7 watchdog)
        if hub is not None:
            last = hub.last_data_time
            if last > 0:
                self.input_seconds_since_last_data.set(time.time() - last)
            else:
                self.input_seconds_since_last_data.set(-1)
            self.hub_running_status.set(1 if hub.is_running else 0)
        else:
            self.input_seconds_since_last_data.set(-1)
            self.hub_running_status.set(0)

        # Active destinations
        active = sum(1 for d in destinations if d.is_connected)
        self.active_destinations_count.set(active)

        # Service uptime
        self.service_uptime_seconds.set(time.time() - self._service_start_time)


# =====================================================================
# Internal helpers
# =====================================================================


class _DestSnapshot:
    """Lightweight snapshot of cumulative counters for delta computation."""

    __slots__ = (
        "bytes_sent",
        "messages_sent",
        "messages_dropped",
        "messages_filtered",
        "connection_attempts",
        "errors",
    )

    def __init__(
        self,
        bytes_sent: int = 0,
        messages_sent: int = 0,
        messages_dropped: int = 0,
        messages_filtered: int = 0,
        connection_attempts: int = 0,
        errors: int = 0,
    ) -> None:
        self.bytes_sent = bytes_sent
        self.messages_sent = messages_sent
        self.messages_dropped = messages_dropped
        self.messages_filtered = messages_filtered
        self.connection_attempts = connection_attempts
        self.errors = errors


def _inc_delta(counter: Counter, current: int, previous: int) -> None:
    """Increment a Prometheus Counter by the delta (if positive).

    Args:
        counter: A labelled Counter child.
        current: Current cumulative value.
        previous: Previous cumulative value.
    """
    delta = current - previous
    if delta > 0:
        counter.inc(delta)
