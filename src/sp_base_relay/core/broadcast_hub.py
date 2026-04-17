"""BroadcastHub — fan-out coordinator for multi-destination RTCM relay.

Reads RTCM data from a single input source and distributes it to
N destination queues with per-destination message filtering.

Architecture (DR-3):
    [Input Thread] → input_queue → [Broadcast Thread] → dest_queues → [Dest Threads]

Design decisions applied:
- DR-1: Dual-path distribution (raw vs parsed+filtered)
- DR-2: Queue overflow handled by BaseDestination.enqueue (drop newest)
- DR-3: Separate broadcast thread decouples input from destinations
- DR-7: No-data watchdog (WARNING after 30s, Prometheus-ready gauge)
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

from sp_base_relay.core.destinations.base_destination import BaseDestination
from sp_base_relay.core.events import (
    DESTINATION_ADDED,
    DESTINATION_REMOVED,
    HUB_STARTED,
    HUB_STOPPED,
    INPUT_CONNECTED,
    INPUT_DISCONNECTED,
    INPUT_NO_DATA_WARNING,
    INPUT_RECONNECTED,
    INPUT_RECONNECTING,
    EventBus,
)
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.rtcm_decoder import RTCMMessageDecoder


logger = logging.getLogger(__name__)

# Watchdog: warn if no data received for this many seconds (DR-7)
NO_DATA_WARNING_SECONDS = 30.0

# Input queue size — small, just for thread coordination
INPUT_QUEUE_SIZE = 10

# Maximum time to wait for input reconnection before retrying
INPUT_RECONNECT_BASE_DELAY = 2.0
INPUT_RECONNECT_MAX_DELAY = 60.0
INPUT_RECONNECT_MULTIPLIER = 2.0


@dataclass
class BroadcastStats:
    """Hub-level statistics tracked by BroadcastHub."""

    bytes_received: int = 0
    chunks_received: int = 0
    frames_parsed: int = 0
    chunks_distributed: int = 0
    input_reconnect_attempts: int = 0
    input_reconnect_successes: int = 0
    last_data_time: float = 0.0
    started_at: float | None = None
    no_data_warnings: int = 0


class BroadcastHub:
    """Fan-out coordinator between a single input source and N destinations.

    The hub owns two threads:
    - **Input thread**: reads data from the input source and pushes raw
      chunks into an internal ``input_queue``.
    - **Broadcast thread**: reads from ``input_queue``, optionally parses
      RTCM frames for destinations that require filtering, and calls
      ``enqueue()`` on each destination.

    Destination threads are started/stopped by the hub but run
    independently inside each :class:`BaseDestination`.
    """

    def __init__(
        self,
        input_source: InputSource,
        destinations: list[BaseDestination] | None = None,
        input_queue_size: int = INPUT_QUEUE_SIZE,
        event_bus: EventBus | None = None,
    ) -> None:
        """Initialise the broadcast hub.

        Args:
            input_source: The single GPS data source.
            destinations: Destination instances to fan out to. May be empty
                or ``None`` if destinations will be added later via
                :meth:`add_destination`.
            input_queue_size: Internal queue between input and broadcast threads.
            event_bus: Optional event bus for lifecycle event emissions.
        """
        self._input_source = input_source
        self._destinations: list[BaseDestination] = list(destinations or [])
        self._destinations_lock = threading.Lock()
        self._input_queue: queue.Queue[bytes | None] = queue.Queue(
            maxsize=input_queue_size,
        )

        # Event bus (optional — None means no events emitted)
        self._event_bus = event_bus

        # Threading
        self._running = False
        self._stop_event = threading.Event()
        self._input_thread: threading.Thread | None = None
        self._broadcast_thread: threading.Thread | None = None

        # Statistics
        self.stats = BroadcastStats()

        # Frame buffer for RTCM parsing (only used in filtered path)
        self._frame_buffer = b""
        self._frame_buffer_lock = threading.Lock()

        # Pre-compute whether any destination needs parsing (DR-1)
        self._any_needs_parsing = any(
            d.message_filter.requires_parsing for d in self._destinations
        )

        logger.info(
            "BroadcastHub initialised: %s → %d destination(s), parsing=%s",
            input_source.source_type,
            len(self._destinations),
            self._any_needs_parsing,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True while both internal threads are active."""
        return self._running

    @property
    def last_data_time(self) -> float:
        """Epoch timestamp of the last data chunk from the input source."""
        return self.stats.last_data_time

    @property
    def seconds_since_last_data(self) -> float:
        """Seconds elapsed since the last data chunk (DR-7 gauge)."""
        if self.stats.last_data_time == 0.0:
            return 0.0
        return time.time() - self.stats.last_data_time

    @property
    def destinations(self) -> list[BaseDestination]:
        """Registered destinations (read-only copy)."""
        with self._destinations_lock:
            return list(self._destinations)

    # ------------------------------------------------------------------
    # Dynamic destination management (v2.1)
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, message: str, **payload: Any) -> None:
        """Emit an event if an event bus is configured."""
        if self._event_bus is not None:
            self._event_bus.emit(event_type, message, **payload)

    def add_destination(self, dest: BaseDestination) -> None:
        """Add a destination while the hub is running (hot-add).

        The destination thread is started immediately if the hub is
        running. Thread-safe — can be called from any thread.

        Args:
            dest: The destination to add.

        Raises:
            ValueError: If a destination with the same name already exists.
        """
        with self._destinations_lock:
            for existing in self._destinations:
                if existing.name == dest.name:
                    raise ValueError(
                        f"Destination '{dest.name}' already exists"
                    )
            self._destinations.append(dest)
            self._recalculate_needs_parsing()

        if self._running:
            dest.start()

        self._emit(
            DESTINATION_ADDED,
            f"Destination '{dest.name}' added",
            destination=dest.name,
            destination_type=dest.destination_type,
        )
        logger.info("Destination '%s' added (running=%s)", dest.name, self._running)

    def remove_destination(self, name: str) -> BaseDestination | None:
        """Remove and stop a destination by name (hot-remove).

        Thread-safe — can be called from any thread.

        Args:
            name: Name of the destination to remove.

        Returns:
            The removed destination, or None if not found.
        """
        removed: BaseDestination | None = None
        with self._destinations_lock:
            for i, dest in enumerate(self._destinations):
                if dest.name == name:
                    removed = self._destinations.pop(i)
                    self._recalculate_needs_parsing()
                    break

        if removed is not None:
            removed.stop()
            self._emit(
                DESTINATION_REMOVED,
                f"Destination '{name}' removed",
                destination=name,
            )
            logger.info("Destination '%s' removed", name)

        return removed

    def stop_destination(self, name: str) -> bool:
        """Stop a specific destination's thread (keeps it in the list).

        Sets ``enabled=False`` and stops the thread. The destination
        remains registered and can be restarted with :meth:`start_destination`.

        Args:
            name: Name of the destination to stop.

        Returns:
            True if the destination was found and stopped.
        """
        dest = self.get_destination(name)
        if dest is None:
            return False
        dest.enabled = False
        dest.stop()
        logger.info("Destination '%s' stopped", name)
        return True

    def start_destination(self, name: str) -> bool:
        """Restart a previously stopped destination.

        Sets ``enabled=True`` and starts the thread.

        Args:
            name: Name of the destination to start.

        Returns:
            True if the destination was found and started.
        """
        dest = self.get_destination(name)
        if dest is None:
            return False
        dest.enabled = True
        dest.start()
        logger.info("Destination '%s' started", name)
        return True

    def get_destination(self, name: str) -> BaseDestination | None:
        """Look up a destination by name.

        Args:
            name: Destination name.

        Returns:
            The destination, or None if not found.
        """
        with self._destinations_lock:
            for dest in self._destinations:
                if dest.name == name:
                    return dest
        return None

    def get_destination_names(self) -> list[str]:
        """Return names of all registered destinations."""
        with self._destinations_lock:
            return [d.name for d in self._destinations]

    def _recalculate_needs_parsing(self) -> None:
        """Recalculate whether any destination needs RTCM parsing.

        Must be called while holding ``_destinations_lock``.
        """
        self._any_needs_parsing = any(
            d.message_filter.requires_parsing for d in self._destinations
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the hub: connect input, start destinations, launch threads.

        Raises:
            RuntimeError: If already running.
            ConnectionError: If the input source cannot connect.
        """
        if self._running:
            logger.warning("BroadcastHub.start() called while already running")
            return

        logger.info("BroadcastHub starting…")

        # Connect input source
        if not self._input_source.is_connected:
            if not self._input_source.connect():
                raise ConnectionError(
                    f"Failed to connect input source "
                    f"({self._input_source.source_type})"
                )
        self._emit(
            INPUT_CONNECTED,
            "Input source connected",
            source_type=self._input_source.source_type,
        )

        # Start all destination threads
        with self._destinations_lock:
            for dest in self._destinations:
                dest.start()

        # Reset state
        self._running = True
        self._stop_event.clear()
        self.stats.started_at = time.time()
        with self._frame_buffer_lock:
            self._frame_buffer = b""

        # Launch internal threads
        self._input_thread = threading.Thread(
            target=self._input_thread_worker,
            name="BroadcastHub-Input",
            daemon=True,
        )
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop,
            name="BroadcastHub-Broadcast",
            daemon=True,
        )
        self._input_thread.start()
        self._broadcast_thread.start()

        self._emit(
            HUB_STARTED,
            "BroadcastHub started",
            destinations=self.get_destination_names(),
        )
        logger.info("BroadcastHub started")

    def stop(self) -> None:
        """Stop the hub gracefully: signal threads, stop destinations."""
        if not self._running:
            return

        logger.info("BroadcastHub stopping…")
        self._running = False
        self._stop_event.set()

        # Wake the broadcast thread with a poison pill
        try:
            self._input_queue.put_nowait(None)
        except queue.Full:
            try:
                self._input_queue.get_nowait()
                self._input_queue.put_nowait(None)
            except queue.Empty:
                pass

        # Wait for internal threads
        if self._input_thread is not None and self._input_thread.is_alive():
            self._input_thread.join(timeout=5.0)
        if self._broadcast_thread is not None and self._broadcast_thread.is_alive():
            self._broadcast_thread.join(timeout=5.0)

        # Stop destination threads
        with self._destinations_lock:
            for dest in self._destinations:
                dest.stop()

        # Disconnect input source
        try:
            self._input_source.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error disconnecting input source: %s", exc)

        # Drain input queue
        while True:
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break

        # Clear frame buffer
        with self._frame_buffer_lock:
            self._frame_buffer = b""

        self.stats.started_at = None
        self._emit(HUB_STOPPED, "BroadcastHub stopped")
        logger.info("BroadcastHub stopped")

    # ------------------------------------------------------------------
    # Input thread
    # ------------------------------------------------------------------

    def _input_thread_worker(self) -> None:
        """Read data from the input source and push into ``_input_queue``."""
        logger.debug("Input thread started")

        while self._running and not self._stop_event.is_set():
            # Reconnect loop if input is down
            if not self._input_source.is_connected:
                self._emit(
                    INPUT_DISCONNECTED,
                    "Input source disconnected",
                    source_type=self._input_source.source_type,
                )
                self._reconnect_input()
                if not self._input_source.is_connected:
                    # Reconnect failed — wait before retrying
                    continue
                # Reconnected — resume reading

            try:
                data = self._input_source.read_data(timeout=1.0)
            except Exception as exc:  # noqa: BLE001
                logger.error("Input read error: %s", exc)
                try:
                    self._input_source.disconnect()
                except Exception:  # noqa: BLE001
                    pass
                continue

            if data is None:
                # No data available within timeout — loop back
                continue

            # Push into internal queue (non-blocking to avoid stalling
            # the input source if broadcast is slow)
            try:
                self._input_queue.put(data, timeout=0.5)
            except queue.Full:
                logger.warning("Input queue full — dropping chunk (%d bytes)", len(data))
                continue

        logger.debug("Input thread exited")

    def _reconnect_input(self) -> None:
        """Attempt to reconnect the input source with exponential backoff."""
        delay = INPUT_RECONNECT_BASE_DELAY

        while self._running and not self._stop_event.is_set():
            self.stats.input_reconnect_attempts += 1
            logger.info(
                "Attempting input reconnect (#%d)…",
                self.stats.input_reconnect_attempts,
            )

            self._emit(
                INPUT_RECONNECTING,
                f"Attempting input reconnect #{self.stats.input_reconnect_attempts}",
                attempt=self.stats.input_reconnect_attempts,
            )

            try:
                if self._input_source.connect():
                    self.stats.input_reconnect_successes += 1
                    self._emit(
                        INPUT_RECONNECTED,
                        "Input source reconnected",
                        source_type=self._input_source.source_type,
                        attempt=self.stats.input_reconnect_attempts,
                    )
                    logger.info("Input source reconnected")
                    return
            except Exception as exc:  # noqa: BLE001
                logger.warning("Input reconnect failed: %s", exc)

            # Backoff
            logger.info("Waiting %.1fs before next reconnect attempt", delay)
            if self._stop_event.wait(timeout=delay):
                return  # Stop requested
            delay = min(delay * INPUT_RECONNECT_MULTIPLIER, INPUT_RECONNECT_MAX_DELAY)

    # ------------------------------------------------------------------
    # Broadcast thread
    # ------------------------------------------------------------------

    def _broadcast_loop(self) -> None:
        """Read chunks from ``_input_queue`` and fan out to destinations."""
        logger.debug("Broadcast thread started")

        while self._running and not self._stop_event.is_set():
            try:
                data = self._input_queue.get(timeout=1.0)
            except queue.Empty:
                self._check_no_data_watchdog()
                continue

            if data is None:
                break

            self.stats.bytes_received += len(data)
            self.stats.chunks_received += 1
            self.stats.last_data_time = time.time()

            # Distribute to destinations (DR-1 dual path)
            if self._any_needs_parsing:
                self._distribute_filtered(data)
            else:
                self._distribute_raw(data)

            self.stats.chunks_distributed += 1

        logger.debug("Broadcast thread exited")

    # ------------------------------------------------------------------
    # Dual-path distribution (DR-1)
    # ------------------------------------------------------------------

    def _distribute_raw(self, data: bytes) -> None:
        """Fast path: all destinations use pass_all — forward raw chunks."""
        with self._destinations_lock:
            snapshot = list(self._destinations)
        for dest in snapshot:
            if dest.enabled:
                dest.enqueue(data)

    def _distribute_filtered(self, data: bytes) -> None:
        """Slow path: at least one destination uses filtering.

        1. Parse RTCM frames from the accumulated buffer.
        2. For each destination:
           - ``pass_all`` → enqueue the original raw chunk (no overhead).
           - filtered  → enqueue only the frames that pass its filter.
        """
        # Parse frames
        parsed_frames = self._parse_frames(data)

        with self._destinations_lock:
            snapshot = list(self._destinations)

        for dest in snapshot:
            if not dest.enabled:
                continue

            if not dest.message_filter.requires_parsing:
                # pass_all destination — gets the raw chunk as-is
                dest.enqueue(data)
            else:
                # Filtered destination — apply filter
                if not parsed_frames:
                    # No complete frames parsed yet; nothing to send
                    continue
                accepted = dest.message_filter.filter_frames(parsed_frames)
                filtered_count = len(parsed_frames) - len(accepted)
                dest.stats.messages_filtered += filtered_count
                for frame_bytes in accepted:
                    dest.enqueue(frame_bytes)

    def _parse_frames(self, data: bytes) -> list[tuple[int, bytes]]:
        """Parse complete RTCM frames from the accumulated buffer.

        Appends *data* to the internal frame buffer and extracts any
        complete frames.  Returns ``(message_id, frame_bytes)`` tuples.

        Args:
            data: Raw chunk from the input source.

        Returns:
            List of (message_id, raw_frame_bytes) tuples for complete frames.
        """
        with self._frame_buffer_lock:
            self._frame_buffer += data
            return self._extract_complete_rtcm_frames()

    def _extract_complete_rtcm_frames(self) -> list[tuple[int, bytes]]:
        """Extract complete RTCM frames from ``_frame_buffer``.

        Must be called while holding ``_frame_buffer_lock``.

        Returns:
            List of (message_id, frame_bytes) tuples.
        """
        results: list[tuple[int, bytes]] = []
        offset = 0
        buf = self._frame_buffer
        buf_len = len(buf)

        while offset < buf_len:
            # Look for RTCM preamble (0xD3)
            if buf[offset] != 0xD3:
                offset += 1
                continue

            # Need at least 3 bytes for header
            if offset + 3 > buf_len:
                break

            # Extract 10-bit message length
            length = ((buf[offset + 1] & 0x03) << 8) | buf[offset + 2]
            if length > 1023:
                offset += 1
                continue

            # Full frame = 3 (header) + length + 3 (CRC)
            frame_len = 3 + length + 3
            if offset + frame_len > buf_len:
                break  # Incomplete — keep for next call

            frame = buf[offset : offset + frame_len]

            if RTCMMessageDecoder.is_valid_rtcm_frame(frame):
                msg_id = RTCMMessageDecoder.extract_message_id(frame)
                if msg_id is not None:
                    results.append((msg_id, frame))
                    self.stats.frames_parsed += 1
                offset += frame_len
            else:
                offset += 1  # Skip invalid byte

        # Keep leftover for next chunk
        self._frame_buffer = buf[offset:]
        return results

    # ------------------------------------------------------------------
    # Watchdog (DR-7)
    # ------------------------------------------------------------------

    def _check_no_data_watchdog(self) -> None:
        """Log a WARNING if no data has been received for 30+ seconds."""
        if self.stats.last_data_time == 0.0:
            # Never received data — use start time as baseline
            if self.stats.started_at is None:
                return
            elapsed = time.time() - self.stats.started_at
        else:
            elapsed = time.time() - self.stats.last_data_time

        if elapsed >= NO_DATA_WARNING_SECONDS:
            self.stats.no_data_warnings += 1
            self._emit(
                INPUT_NO_DATA_WARNING,
                f"No data for {elapsed:.0f}s",
                elapsed_seconds=elapsed,
                warning_count=self.stats.no_data_warnings,
            )
            # Only log every ~30s to avoid log flooding
            if self.stats.no_data_warnings <= 1 or self.stats.no_data_warnings % 10 == 0:
                logger.warning(
                    "No data from input source for %.0f seconds "
                    "(warning #%d)",
                    elapsed,
                    self.stats.no_data_warnings,
                )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_detailed_status(self) -> dict[str, Any]:
        """Build a status dictionary for diagnostics / API exposure."""
        uptime: float | None = None
        if self.stats.started_at is not None:
            uptime = time.time() - self.stats.started_at

        dest_statuses: list[dict[str, Any]] = []
        with self._destinations_lock:
            snapshot = list(self._destinations)
        for dest in snapshot:
            s = dest.get_stats()
            dest_statuses.append(
                {
                    "name": dest.name,
                    "type": dest.destination_type,
                    "enabled": dest.enabled,
                    "running": dest.is_running,
                    "filter": dest.message_filter.mode.value,
                    "queue_depth": s.queue_depth,
                    "bytes_sent": s.bytes_sent,
                    "messages_sent": s.messages_sent,
                    "messages_dropped": s.messages_dropped,
                    "messages_filtered": s.messages_filtered,
                    "errors": s.errors,
                }
            )

        return {
            "hub": {
                "running": self._running,
                "uptime_seconds": uptime,
                "input_connected": self._input_source.is_connected,
                "seconds_since_last_data": self.seconds_since_last_data,
            },
            "stats": {
                "bytes_received": self.stats.bytes_received,
                "chunks_received": self.stats.chunks_received,
                "chunks_distributed": self.stats.chunks_distributed,
                "frames_parsed": self.stats.frames_parsed,
                "input_reconnects": self.stats.input_reconnect_attempts,
                "no_data_warnings": self.stats.no_data_warnings,
            },
            "destinations": dest_statuses,
        }
