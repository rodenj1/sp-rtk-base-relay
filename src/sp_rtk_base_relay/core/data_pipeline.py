"""Data pipeline coordinator for SP-Base-Relay.

This module provides the main data pipeline coordination between input sources
and the RTCM client, managing connections, data flow, and error recovery with
automatic reconnection for both sides.
"""

import logging
import queue
import threading
import time
from typing import Any
from dataclasses import dataclass
from collections.abc import Callable

from .input_sources.base_input import InputSource
from .rtcm_client import RTCMClient
from ..exceptions import ServiceError
from ..rtcm_decoder import RTCMMessageDecoder


logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Data pipeline statistics and metrics."""

    pipeline_starts: int = 0
    successful_starts: int = 0
    pipeline_stops: int = 0
    restart_attempts: int = 0
    input_errors: int = 0
    rtcm_errors: int = 0
    coordination_errors: int = 0
    bytes_processed: int = 0
    messages_processed: int = 0
    last_data_time: float = 0.0
    uptime_start: float | None = None


class DataPipelineCoordinator:
    """Coordinates data flow between input sources and RTCM client.

    Implements a 3-thread architecture:
    - Input Thread: Dedicated thread for reading data from input source
    - Coordinator Thread: Main thread managing connections and sending data
    - RTCM Heartbeat Thread: Already exists in RTCMClient for heartbeat monitoring

    Features:
    - No data buffering (small queue for thread coordination only)
    - Coordinated restart: both connections restart together on any failure
    - Automatic reconnection with proper error handling
    - Comprehensive statistics and monitoring
    """

    def __init__(
        self,
        input_source: InputSource,
        rtcm_client: RTCMClient,
        restart_callback: Callable[[], None] | None = None,
        metrics_collector: Any | None = None,
    ):
        """Initialize data pipeline coordinator.

        Args:
            input_source: Input source for reading RTCM data
            rtcm_client: RTCM client for server communication
            restart_callback: Optional callback for external restart coordination
            metrics_collector: Optional MetricsCollector for performance tracking
        """
        self.input_source = input_source
        self.rtcm_client = rtcm_client
        self.restart_callback = restart_callback
        self.metrics_collector = metrics_collector

        # Threading coordination
        self.data_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=10)
        self.running = False
        self.input_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._restart_requested = threading.Event()

        # Statistics and monitoring
        self.stats = PipelineStats()

        # Thread synchronization
        self._stats_lock = threading.Lock()

        # RTCM frame buffer for accurate metrics decoding
        # Accumulates partial chunks to extract complete RTCM frames
        self._frame_buffer = b""
        self._frame_buffer_lock = threading.Lock()

        logger.info(
            f"Initialized data pipeline coordinator: "
            f"{input_source.source_type} -> RTCM Client"
        )

    @property
    def is_running(self) -> bool:
        """Check if pipeline is currently running."""
        return self.running

    @property
    def is_healthy(self) -> bool:
        """Check if both connections are healthy."""
        return (
            self.input_source.is_connected
            and self.rtcm_client.is_connected
            and self.running
        )

    @property
    def pipeline_statistics(self) -> PipelineStats:
        """Get pipeline statistics."""
        with self._stats_lock:
            return self.stats

    def start_relay(self) -> None:
        """Start the data relay pipeline.

        Establishes both connections and starts data flow coordination.
        Blocks until pipeline stops or fails.

        Raises:
            ServiceError: If initial connection setup fails
        """
        if self.running:
            logger.warning("Pipeline already running")
            return

        logger.info("Starting data pipeline relay")

        with self._stats_lock:
            self.stats.pipeline_starts += 1

        try:
            # Connect input source first
            if not self.input_source.connect():
                raise ServiceError(
                    f"Failed to connect {self.input_source.source_type} input source"
                )

            # Connect RTCM client
            if not self.rtcm_client.connect():
                # Cleanup input source on RTCM failure
                self.input_source.disconnect()
                raise ServiceError("Failed to connect RTCM server")

            # Both connections successful
            self.running = True
            self._stop_event.clear()
            self._restart_requested.clear()

            # Clear frame buffer on new start
            with self._frame_buffer_lock:
                self._frame_buffer = b""

            with self._stats_lock:
                self.stats.successful_starts += 1
                self.stats.uptime_start = time.time()

            # Start input reading thread
            self.input_thread = threading.Thread(
                target=self._input_thread_worker, name="DataPipelineInput", daemon=False
            )
            self.input_thread.start()

            logger.info("Data pipeline started successfully")

            # Main coordinator loop (blocks here)
            self._coordinator_loop()

        except Exception as e:
            logger.error(f"Failed to start data pipeline: {e}")
            self._cleanup_connections()
            raise ServiceError(f"Pipeline startup failed: {e}")
        finally:
            self._finalize_shutdown()

    def stop_relay(self) -> None:
        """Stop the data relay pipeline gracefully."""
        if not self.running:
            return

        logger.info("Stopping data pipeline relay")

        # Signal threads to stop
        self.running = False
        self._stop_event.set()

        # Wake up coordinator loop if waiting
        try:
            self.data_queue.put(None, timeout=1)
        except queue.Full:
            pass  # Queue is full, coordinator will stop anyway

        with self._stats_lock:
            self.stats.pipeline_stops += 1

    def request_restart(self) -> None:
        """Request pipeline restart due to error condition."""
        logger.warning("Pipeline restart requested")

        with self._stats_lock:
            self.stats.restart_attempts += 1

        self._restart_requested.set()
        self.stop_relay()

    def _input_thread_worker(self) -> None:
        """Input thread worker - continuously reads data from input source."""
        logger.debug("Input thread started")

        try:
            while self.running and not self._stop_event.is_set():
                try:
                    # Check if input source is still connected
                    if not self.input_source.is_connected:
                        logger.warning("Input source disconnected, triggering restart")
                        self._handle_input_error("Input source connection lost")
                        break

                    # Read data from input source (with timeout)
                    data = self.input_source.read_data(timeout=1.0)

                    if data is not None:
                        # Put data in queue for coordinator (non-blocking)
                        try:
                            self.data_queue.put(data, timeout=0.1)
                        except queue.Full:
                            # Queue full - coordinator might be stuck, trigger restart
                            logger.warning("Data queue full, triggering restart")
                            self._handle_input_error("Data queue overflow")
                            break

                    # Small sleep to prevent busy waiting when no data
                    if data is None:
                        time.sleep(0.01)

                except Exception as e:
                    logger.error(f"Input thread error: {e}")
                    self._handle_input_error(f"Input thread exception: {e}")
                    break

        except Exception as e:
            logger.error(f"Critical input thread error: {e}")
            self._handle_input_error(f"Critical input thread error: {e}")
        finally:
            logger.debug("Input thread stopped")

    def _coordinator_loop(self) -> None:
        """Main coordinator loop - manages data flow and connection health."""
        logger.debug("Coordinator loop started")

        try:
            while self.running and not self._stop_event.is_set():
                try:
                    # Get data from input thread with timeout
                    try:
                        data = self.data_queue.get(timeout=1.0)
                        receive_time = time.perf_counter()  # Mark receive time for latency
                    except queue.Empty:
                        # No data available, check connection health
                        if not self._check_connections_health():
                            break
                        continue

                    # Check for shutdown signal
                    if data is None or not self.running:
                        break

                    # Verify RTCM client is still connected
                    if not self.rtcm_client.is_connected:
                        logger.info("RTCM client disconnected, initiating reconnection")
                        self._handle_rtcm_error("RTCM client connection lost")
                        break

                    # Send data to RTCM client
                    if self.rtcm_client.send_rtcm_data(data):
                        send_time = time.perf_counter()  # Mark send completion time

                        # POST-SEND METRICS (zero relay impact)
                        # Record latency metric
                        if self.metrics_collector:
                            relay_latency = send_time - receive_time
                            self.metrics_collector.record_relay_latency(relay_latency)

                        # Decode message IDs using frame buffer for accurate metrics
                        if self.metrics_collector:
                            # Add chunk to frame buffer
                            with self._frame_buffer_lock:
                                self._frame_buffer += data

                            # Extract complete RTCM frames from buffer
                            complete_frames = self._extract_complete_rtcm_frames()

                            # Decode each complete frame
                            for frame in complete_frames:
                                msg_ids = RTCMMessageDecoder.extract_all_message_ids(frame)
                                if msg_ids:
                                    # Count each message ID found
                                    for msg_id in msg_ids:
                                        self.metrics_collector.increment_message_id_counter(msg_id)
                                    logger.debug(
                                        f"Decoded {len(msg_ids)} RTCM message IDs from "
                                        f"{len(frame)}-byte frame"
                                    )
                                else:
                                    # Complete frame but decode failed (unusual)
                                    self.metrics_collector.increment_decode_failures()
                                    logger.warning(
                                        f"Failed to decode {len(frame)}-byte complete frame"
                                    )

                        # Update pipeline statistics
                        with self._stats_lock:
                            self.stats.bytes_processed += len(data)
                            self.stats.messages_processed += 1
                            self.stats.last_data_time = time.time()

                        logger.debug(f"Processed {len(data)} bytes through pipeline")
                    else:
                        # RTCM send failed
                        logger.warning("RTCM data send failed, triggering restart")
                        self._handle_rtcm_error("RTCM data transmission failed")
                        break

                except Exception as e:
                    logger.error(f"Coordinator loop error: {e}")
                    self._handle_coordination_error(f"Coordinator exception: {e}")
                    break

        except Exception as e:
            logger.error(f"Critical coordinator error: {e}")
            self._handle_coordination_error(f"Critical coordinator error: {e}")
        finally:
            logger.debug("Coordinator loop stopped")

    def _extract_complete_rtcm_frames(self) -> list[bytes]:
        """Extract complete RTCM frames from the frame buffer.

        This method processes the accumulated frame buffer to find and extract
        complete RTCM v3 frames. It handles:
        - Multiple frames in buffer
        - Partial frames at the end (kept for next chunk)
        - Invalid data between frames (skipped)

        Returns:
            List of complete RTCM frames (may be empty)

        Note:
            This method is called AFTER data has been sent to the RTCM server,
            so it has zero impact on relay latency. It's purely for metrics.
        """
        complete_frames: list[bytes] = []

        with self._frame_buffer_lock:
            offset = 0
            buffer_len = len(self._frame_buffer)

            while offset < buffer_len:
                # Look for RTCM preamble (0xD3)
                if self._frame_buffer[offset] != 0xD3:
                    offset += 1
                    continue

                # Need at least 3 bytes to read length
                if offset + 3 > buffer_len:
                    # Not enough data for header, keep for next chunk
                    break

                # Extract message length (10 bits from bytes 1-2)
                length = (
                    (self._frame_buffer[offset + 1] & 0x03) << 8
                ) | self._frame_buffer[offset + 2]

                # Calculate expected frame length: 3 (header) + length + 3 (CRC)
                expected_frame_length = 3 + length + 3

                # Validate length (RTCM v3 max is 1023 bytes)
                if length > 1023:
                    # Invalid length, skip this byte and continue searching
                    offset += 1
                    continue

                # Check if we have the complete frame
                if offset + expected_frame_length > buffer_len:
                    # Incomplete frame, keep for next chunk
                    break

                # Extract complete frame
                frame = self._frame_buffer[offset : offset + expected_frame_length]
                
                # Validate frame before adding to results
                if RTCMMessageDecoder.is_valid_rtcm_frame(frame):
                    complete_frames.append(frame)
                    # Move offset past this valid frame
                    offset += expected_frame_length
                else:
                    # Invalid frame - skip this byte and keep searching
                    logger.debug(f"Invalid RTCM frame at offset {offset}, skipping")
                    offset += 1

            # Keep remaining incomplete data for next chunk
            self._frame_buffer = self._frame_buffer[offset:]

            # Log buffer statistics if frames were extracted
            if complete_frames:
                logger.debug(
                    f"Extracted {len(complete_frames)} complete RTCM frames, "
                    f"{len(self._frame_buffer)} bytes remaining in buffer"
                )

        return complete_frames

    def _check_connections_health(self) -> bool:
        """Check health of both connections.

        Returns:
            True if both connections are healthy
        """
        input_healthy = self.input_source.is_connected
        rtcm_healthy = self.rtcm_client.is_connected

        if not input_healthy:
            logger.warning("Input source health check failed")
            self._handle_input_error("Input source health check failed")
            return False

        if not rtcm_healthy:
            logger.warning("RTCM client health check failed")
            self._handle_rtcm_error("RTCM client health check failed")
            return False

        return True

    def _handle_input_error(self, error_msg: str) -> None:
        """Handle input source errors.

        Args:
            error_msg: Error description
        """
        logger.error(f"Input source error: {error_msg}")

        with self._stats_lock:
            self.stats.input_errors += 1

        self.request_restart()

    def _handle_rtcm_error(self, error_msg: str) -> None:
        """Handle RTCM client errors.

        Args:
            error_msg: Error description
        """
        logger.error(f"RTCM client error: {error_msg}")

        with self._stats_lock:
            self.stats.rtcm_errors += 1

        self.request_restart()

    def _handle_coordination_error(self, error_msg: str) -> None:
        """Handle coordination errors.

        Args:
            error_msg: Error description
        """
        logger.error(f"Coordination error: {error_msg}")

        with self._stats_lock:
            self.stats.coordination_errors += 1

        self.request_restart()

    def _cleanup_connections(self) -> None:
        """Cleanup both connections."""
        logger.debug("Cleaning up connections")

        # Disconnect RTCM client first (stops heartbeat thread)
        try:
            self.rtcm_client.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting RTCM client: {e}")

        # Disconnect input source
        try:
            self.input_source.disconnect()
        except Exception as e:
            logger.warning(f"Error disconnecting input source: {e}")

    def _finalize_shutdown(self) -> None:
        """Finalize pipeline shutdown."""
        logger.debug("Finalizing pipeline shutdown")

        # Wait for input thread to finish
        if self.input_thread and self.input_thread.is_alive():
            self.input_thread.join(timeout=2.0)
            if self.input_thread.is_alive():
                logger.warning("Input thread did not shut down cleanly")

        # Cleanup connections
        self._cleanup_connections()

        # Clear queue
        try:
            while not self.data_queue.empty():
                self.data_queue.get_nowait()
        except queue.Empty:
            pass

        # Clear frame buffer
        with self._frame_buffer_lock:
            if len(self._frame_buffer) > 0:
                logger.debug(
                    f"Discarding {len(self._frame_buffer)} bytes from frame buffer"
                )
            self._frame_buffer = b""

        # Update statistics
        with self._stats_lock:
            self.stats.uptime_start = None

        self.running = False

        # Call restart callback if restart was requested
        if self._restart_requested.is_set() and self.restart_callback:
            logger.info("Calling restart callback")
            try:
                self.restart_callback()
            except Exception as e:
                logger.error(f"Restart callback failed: {e}")

        logger.info("Data pipeline shutdown completed")

    def get_detailed_status(self) -> dict[str, Any]:
        """Get detailed pipeline status information.

        Returns:
            Dictionary with comprehensive status information
        """
        status: dict[str, Any] = {
            "pipeline": {
                "running": self.is_running,
                "healthy": self.is_healthy,
                "restart_requested": self._restart_requested.is_set(),
            },
            "input_source": {
                "connected": self.input_source.is_connected,
                "type": self.input_source.source_type,
                "connection_info": self.input_source.get_connection_info(),
                "statistics": self.input_source.connection_statistics,
                "last_error": (
                    str(self.input_source.last_error)
                    if self.input_source.last_error
                    else None
                ),
            },
            "rtcm_client": {
                "connected": self.rtcm_client.is_connected,
                "state": self.rtcm_client.connection_state.value,
                "statistics": self.rtcm_client.connection_statistics,
            },
            "pipeline_statistics": self.pipeline_statistics,
            "queue_status": {
                "size": self.data_queue.qsize(),
                "max_size": self.data_queue.maxsize,
            },
        }

        # Add uptime if running
        if self.stats.uptime_start is not None:
            uptime_seconds = time.time() - self.stats.uptime_start
            status["pipeline"]["uptime_seconds"] = uptime_seconds

        return status
