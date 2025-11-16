"""Prometheus metrics collection and export for SP-Base-Relay.

This module provides comprehensive metrics collection for monitoring
the RTCM relay service using Prometheus.
"""

import logging
import time
from typing import Any
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)


logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects and exports Prometheus metrics for SP-Base-Relay.

    Provides comprehensive metrics for:
    - Connection status and health
    - Data flow and throughput
    - Error rates and types
    - System uptime and performance
    """

    def __init__(self, namespace: str = "sp_base_relay"):
        """Initialize metrics collector.

        Args:
            namespace: Metric name prefix
        """
        self.namespace = namespace
        self._running = False

        # Connection metrics
        self.rtcm_connection_status = Gauge(
            f"{namespace}_rtcm_connection_status",
            "RTCM server connection status (1=connected, 0=disconnected)",
        )

        self.rtcm_connection_attempts_total = Counter(
            f"{namespace}_rtcm_connection_attempts_total",
            "Total RTCM server connection attempts",
        )

        self.rtcm_successful_connections_total = Counter(
            f"{namespace}_rtcm_successful_connections_total",
            "Total successful RTCM server connections",
        )

        self.rtcm_authentication_failures_total = Counter(
            f"{namespace}_rtcm_authentication_failures_total",
            "Total RTCM authentication failures",
        )

        self.rtcm_heartbeat_timeouts_total = Counter(
            f"{namespace}_rtcm_heartbeat_timeouts_total",
            "Total RTCM heartbeat timeout events",
        )

        # Data flow metrics
        self.rtcm_messages_sent_total = Counter(
            f"{namespace}_rtcm_messages_sent_total",
            "Total RTCM messages sent to server",
        )

        self.rtcm_bytes_sent_total = Counter(
            f"{namespace}_rtcm_bytes_sent_total", "Total bytes sent to RTCM server"
        )

        self.pipeline_messages_processed_total = Counter(
            f"{namespace}_pipeline_messages_processed_total",
            "Total messages processed through pipeline",
        )

        self.pipeline_bytes_processed_total = Counter(
            f"{namespace}_pipeline_bytes_processed_total",
            "Total bytes processed through pipeline",
        )

        # Input source metrics
        self.input_connection_status = Gauge(
            f"{namespace}_input_connection_status",
            "Input source connection status (1=connected, 0=disconnected)",
        )

        self.input_bytes_read_total = Counter(
            f"{namespace}_input_bytes_read_total", "Total bytes read from input source"
        )

        self.input_errors_total = Counter(
            f"{namespace}_input_errors_total", "Total input source errors"
        )

        # Pipeline metrics
        self.pipeline_running_status = Gauge(
            f"{namespace}_pipeline_running_status",
            "Pipeline running status (1=running, 0=stopped)",
        )

        self.pipeline_restarts_total = Counter(
            f"{namespace}_pipeline_restarts_total", "Total pipeline restart attempts"
        )

        self.pipeline_errors_total = Counter(
            f"{namespace}_pipeline_errors_total",
            "Total pipeline errors by type",
            ["error_type"],
        )

        # Health metrics
        self.rtcm_heartbeat_last_received_timestamp = Gauge(
            f"{namespace}_rtcm_heartbeat_last_received_timestamp",
            "Unix timestamp of last RTCM heartbeat received",
        )

        self.service_uptime_seconds = Gauge(
            f"{namespace}_service_uptime_seconds", "Service uptime in seconds"
        )

        self.pipeline_uptime_seconds = Gauge(
            f"{namespace}_pipeline_uptime_seconds",
            "Current pipeline session uptime in seconds",
        )

        # Relay performance metrics
        self.relay_latency_seconds = Histogram(
            f"{namespace}_relay_latency_seconds",
            "End-to-end relay latency from input read to RTCM send",
            buckets=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        )

        self.rtcm_messages_by_id_total = Counter(
            f"{namespace}_rtcm_messages_by_id_total",
            "Total RTCM messages sent by message ID",
            ["message_id"],
        )

        self.rtcm_message_decode_failures_total = Counter(
            f"{namespace}_rtcm_message_decode_failures_total",
            "Total RTCM message decode failures",
        )

        # Service start time for uptime calculation
        self._service_start_time = time.time()

        logger.info("Metrics collector initialized")

    def start_metrics_server(self, port: int = 9090, host: str = "0.0.0.0") -> None:
        """Start Prometheus metrics HTTP server.

        Args:
            port: Port to listen on
            host: Host to bind to
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
        """Stop metrics server."""
        if not self._running:
            return

        self._running = False
        logger.info("Metrics server stopped")

    def update_from_rtcm_stats(self, stats: Any, prev_stats: Any | None = None) -> None:
        """Update metrics from RTCM client statistics.

        Args:
            stats: ConnectionStats from RTCMClient
            prev_stats: Previous stats for calculating deltas (optional)
        """
        # For counters, we increment by the delta since last update
        if prev_stats:
            # Increment by difference
            conn_attempts_delta = (
                stats.connection_attempts - prev_stats.connection_attempts
            )
            if conn_attempts_delta > 0:
                self.rtcm_connection_attempts_total.inc(conn_attempts_delta)

            conn_success_delta = (
                stats.successful_connections - prev_stats.successful_connections
            )
            if conn_success_delta > 0:
                self.rtcm_successful_connections_total.inc(conn_success_delta)

            auth_fail_delta = (
                stats.authentication_failures - prev_stats.authentication_failures
            )
            if auth_fail_delta > 0:
                self.rtcm_authentication_failures_total.inc(auth_fail_delta)

            hb_timeout_delta = stats.heartbeat_timeouts - prev_stats.heartbeat_timeouts
            if hb_timeout_delta > 0:
                self.rtcm_heartbeat_timeouts_total.inc(hb_timeout_delta)

            msg_sent_delta = stats.messages_sent - prev_stats.messages_sent
            if msg_sent_delta > 0:
                self.rtcm_messages_sent_total.inc(msg_sent_delta)

            bytes_sent_delta = stats.bytes_sent - prev_stats.bytes_sent
            if bytes_sent_delta > 0:
                self.rtcm_bytes_sent_total.inc(bytes_sent_delta)

        # Update health metrics
        if stats.last_heartbeat_time > 0:
            self.rtcm_heartbeat_last_received_timestamp.set(stats.last_heartbeat_time)

    def update_from_pipeline_stats(
        self, stats: Any, prev_stats: Any | None = None
    ) -> None:
        """Update metrics from data pipeline statistics.

        Args:
            stats: PipelineStats from DataPipelineCoordinator
            prev_stats: Previous stats for calculating deltas (optional)
        """
        # For counters, increment by delta
        if prev_stats:
            msg_proc_delta = stats.messages_processed - prev_stats.messages_processed
            if msg_proc_delta > 0:
                self.pipeline_messages_processed_total.inc(msg_proc_delta)

            bytes_proc_delta = stats.bytes_processed - prev_stats.bytes_processed
            if bytes_proc_delta > 0:
                self.pipeline_bytes_processed_total.inc(bytes_proc_delta)

            restart_delta = stats.restart_attempts - prev_stats.restart_attempts
            if restart_delta > 0:
                self.pipeline_restarts_total.inc(restart_delta)

            input_err_delta = stats.input_errors - prev_stats.input_errors
            if input_err_delta > 0:
                self.pipeline_errors_total.labels(error_type="input").inc(
                    input_err_delta
                )

            rtcm_err_delta = stats.rtcm_errors - prev_stats.rtcm_errors
            if rtcm_err_delta > 0:
                self.pipeline_errors_total.labels(error_type="rtcm").inc(rtcm_err_delta)

            coord_err_delta = stats.coordination_errors - prev_stats.coordination_errors
            if coord_err_delta > 0:
                self.pipeline_errors_total.labels(error_type="coordination").inc(
                    coord_err_delta
                )

        # Update pipeline uptime
        if stats.uptime_start is not None:
            uptime = time.time() - stats.uptime_start
            self.pipeline_uptime_seconds.set(uptime)
        else:
            self.pipeline_uptime_seconds.set(0)

    def update_from_input_stats(
        self, stats: Any, prev_stats: Any | None = None
    ) -> None:
        """Update metrics from input source statistics.

        Args:
            stats: ConnectionStatistics from InputSource
            prev_stats: Previous stats for calculating deltas (optional)
        """
        # Update input source data metrics
        if prev_stats:
            bytes_read_delta = stats.bytes_read - prev_stats.bytes_read
            if bytes_read_delta > 0:
                self.input_bytes_read_total.inc(bytes_read_delta)

    def update_connection_status(
        self, rtcm_connected: bool, input_connected: bool
    ) -> None:
        """Update connection status gauges.

        Args:
            rtcm_connected: RTCM server connection status
            input_connected: Input source connection status
        """
        self.rtcm_connection_status.set(1 if rtcm_connected else 0)
        self.input_connection_status.set(1 if input_connected else 0)

    def update_pipeline_status(self, running: bool) -> None:
        """Update pipeline running status.

        Args:
            running: Pipeline running status
        """
        self.pipeline_running_status.set(1 if running else 0)

    def update_service_uptime(self) -> None:
        """Update service uptime metric."""
        uptime = time.time() - self._service_start_time
        self.service_uptime_seconds.set(uptime)

    def record_relay_latency(self, latency_seconds: float) -> None:
        """Record relay latency observation.

        Args:
            latency_seconds: Relay latency in seconds
        """
        self.relay_latency_seconds.observe(latency_seconds)

    def increment_message_id_counter(self, message_id: int) -> None:
        """Increment counter for specific RTCM message ID.

        Args:
            message_id: RTCM message ID (0-4095)
        """
        self.rtcm_messages_by_id_total.labels(message_id=str(message_id)).inc()

    def increment_decode_failures(self) -> None:
        """Increment decode failure counter."""
        self.rtcm_message_decode_failures_total.inc()

    def collect_all_metrics(
        self,
        rtcm_client: Any,
        pipeline_coordinator: Any,
        input_source: Any,
        prev_rtcm_stats: Any | None = None,
        prev_pipeline_stats: Any | None = None,
        prev_input_stats: Any | None = None,
    ) -> tuple[Any, Any, Any]:
        """Collect and update all metrics from components.

        Args:
            rtcm_client: RTCMClient instance
            pipeline_coordinator: DataPipelineCoordinator instance
            input_source: InputSource instance
            prev_rtcm_stats: Previous RTCM stats (optional)
            prev_pipeline_stats: Previous pipeline stats (optional)
            prev_input_stats: Previous input stats (optional)

        Returns:
            Tuple of (current_rtcm_stats, current_pipeline_stats, current_input_stats)
        """
        # Get current stats
        rtcm_stats = rtcm_client.connection_statistics
        pipeline_stats = pipeline_coordinator.pipeline_statistics
        input_stats = input_source.connection_statistics

        # Update RTCM metrics
        self.update_from_rtcm_stats(rtcm_stats, prev_rtcm_stats)

        # Update pipeline metrics
        self.update_from_pipeline_stats(pipeline_stats, prev_pipeline_stats)

        # Update input source metrics
        self.update_from_input_stats(input_stats, prev_input_stats)

        # Update connection status
        self.update_connection_status(
            rtcm_client.is_connected, input_source.is_connected
        )

        # Update pipeline status
        self.update_pipeline_status(pipeline_coordinator.is_running)

        # Update service uptime
        self.update_service_uptime()

        # Return current stats for next iteration
        return (rtcm_stats, pipeline_stats, input_stats)

    @property
    def is_running(self) -> bool:
        """Check if metrics server is running."""
        return self._running
