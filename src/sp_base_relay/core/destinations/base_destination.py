"""Abstract base class for all destination types.

This module defines the BaseDestination ABC that all destination implementations
must inherit from, providing a consistent interface for sending RTCM data
to various output targets (Sure-Path, NTRIP casters, TCP server).

Follows the same pattern as InputSource/InputSourceStats from base_input.py.

Design decisions applied:
- DR-2: Queue overflow — drop newest, clear on reconnect, maxsize=100
"""

import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sp_base_relay.core.message_filter import FilterConfig, MessageFilter


logger = logging.getLogger(__name__)

# Default maximum queue size per destination (DR-2)
DEFAULT_QUEUE_SIZE = 100


@dataclass
class DestinationStats:
    """Per-destination statistics and metrics tracking.

    Thread-safe via atomic field updates. Used by MetricsCollector v2
    to export per-destination Prometheus metrics with
    {destination="name"} labels.
    """

    bytes_sent: int = 0
    messages_sent: int = 0
    messages_dropped: int = 0
    messages_filtered: int = 0
    connection_attempts: int = 0
    successful_connections: int = 0
    connection_failures: int = 0
    errors: int = 0
    last_send_time: float = 0.0
    connected_since: float | None = None
    queue_depth: int = 0
    last_error: str | None = None


class BaseDestination(ABC):
    """Abstract base class for all destination types.

    Each destination runs in its own thread (per architectural decision #1)
    and has its own queue for fault isolation. The BroadcastHub distributes
    data to destination queues, and each destination thread reads from its
    queue and sends data to its remote server.

    Subclasses must implement:
    - _connect(): Establish connection to remote server
    - _disconnect(): Close connection to remote server
    - _send_data(data): Send raw bytes to remote server
    - _is_connected(): Check if connection is alive
    - get_connection_info(): Return connection details for logging

    The base class provides:
    - Queue management (enqueue, clear_queue) with overflow protection (DR-2)
    - Statistics tracking (DestinationStats)
    - Thread lifecycle management (start, stop)
    - MessageFilter integration
    """

    def __init__(
        self,
        name: str,
        destination_type: str,
        filter_config: FilterConfig,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        """Initialize destination base.

        Args:
            name: Unique destination name (used for logging and metrics labels)
            destination_type: Type identifier (surepath, ntrip, tcp_server)
            filter_config: Message filter configuration for this destination
            queue_size: Maximum queue depth (default: 100 per DR-2)
        """
        self.name = name
        self.destination_type = destination_type
        self.enabled: bool = True
        self.stats = DestinationStats()
        self.message_filter = MessageFilter(filter_config)
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=queue_size)
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        logger.info(
            f"Destination '{name}' ({destination_type}) initialized, "
            f"filter={filter_config.mode.value}, queue_size={queue_size}"
        )

    @property
    def is_running(self) -> bool:
        """Check if the destination thread is running."""
        return self._running

    @property
    def queue_depth(self) -> int:
        """Get the current number of items in the queue."""
        return self._queue.qsize()

    def enqueue(self, data: bytes) -> bool:
        """Add data to the destination queue (non-blocking).

        Per DR-2: If the queue is full, silently drop the data for this
        destination. This does NOT affect other destinations.

        Args:
            data: Raw RTCM data bytes to queue for sending

        Returns:
            True if data was queued, False if dropped (queue full)
        """
        try:
            self._queue.put_nowait(data)
            return True
        except queue.Full:
            self.stats.messages_dropped += 1
            logger.debug(
                f"Destination '{self.name}': queue full, dropped data "
                f"({len(data)} bytes, total drops: {self.stats.messages_dropped})"
            )
            return False

    def clear_queue(self) -> int:
        """Clear all pending data from the queue.

        Per DR-2: Called on destination reconnect to discard stale
        RTCM correction data.

        Returns:
            Number of items cleared from the queue
        """
        cleared = 0
        while True:
            try:
                self._queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break

        if cleared > 0:
            logger.info(
                f"Destination '{self.name}': cleared {cleared} items from queue"
            )
        return cleared

    def get_stats(self) -> DestinationStats:
        """Get current destination statistics.

        Returns a snapshot of the current stats with the live queue depth.

        Returns:
            Current DestinationStats with updated queue_depth
        """
        self.stats.queue_depth = self._queue.qsize()
        return self.stats

    def start(self) -> None:
        """Start the destination thread.

        Creates and starts a daemon thread for this destination.
        The thread runs the _run_loop() method which subclasses
        can override for custom behavior.
        """
        if self._running:
            logger.warning(f"Destination '{self.name}' already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"dest-{self.name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Destination '{self.name}' thread started")

    def stop(self) -> None:
        """Stop the destination thread gracefully.

        Signals the thread to stop by sending None to the queue,
        then waits for it to finish.
        """
        if not self._running:
            return

        logger.info(f"Destination '{self.name}' stopping...")
        self._running = False

        # Send poison pill to unblock the queue.get()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # Queue is full — clear one item to make room for poison pill
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(None)
            except queue.Empty:
                pass

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning(
                    f"Destination '{self.name}' thread did not stop within 5 seconds"
                )

        self._disconnect()
        logger.info(f"Destination '{self.name}' stopped")

    def _run_loop(self) -> None:
        """Main destination thread loop.

        Reads data from the queue and sends it. Handles connection
        management and error recovery. Subclasses may override this
        for custom behavior but the default implementation should
        work for most destination types.
        """
        logger.info(f"Destination '{self.name}' run loop started")

        while self._running:
            try:
                # Block for up to 1 second waiting for data
                data = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Poison pill — stop signal
            if data is None:
                break

            # Ensure we're connected
            if not self._is_connected():
                self._attempt_connect()
                if not self._is_connected():
                    # Connection failed — drop this data
                    self.stats.messages_dropped += 1
                    continue

            # Send data
            try:
                self._send_data(data)
                self.stats.bytes_sent += len(data)
                self.stats.messages_sent += 1
                self.stats.last_send_time = time.time()
            except Exception as e:
                self.stats.errors += 1
                self.stats.last_error = str(e)
                logger.error(
                    f"Destination '{self.name}' send error: {e}"
                )
                self._disconnect()

        logger.info(f"Destination '{self.name}' run loop exited")

    def _attempt_connect(self) -> None:
        """Attempt to connect to the remote server.

        Wraps the abstract _connect() method with stats tracking.
        On successful reconnect, clears the queue (DR-2).
        """
        self.stats.connection_attempts += 1
        try:
            self._connect()
            if self._is_connected():
                self.stats.successful_connections += 1
                self.stats.connected_since = time.time()
                self.stats.last_error = None
                # DR-2: Clear stale data on reconnect
                self.clear_queue()
                logger.info(f"Destination '{self.name}' connected")
            else:
                self.stats.connection_failures += 1
                logger.warning(f"Destination '{self.name}' connection failed")
        except Exception as e:
            self.stats.connection_failures += 1
            self.stats.errors += 1
            self.stats.last_error = str(e)
            logger.error(f"Destination '{self.name}' connection error: {e}")

    # --- Abstract methods that subclasses must implement ---

    @abstractmethod
    def _connect(self) -> None:
        """Establish connection to the remote server.

        Must be implemented by subclasses. Should establish the TCP/socket
        connection and perform any authentication handshake.

        Raises:
            DestinationError: If connection fails
        """
        ...

    @abstractmethod
    def _disconnect(self) -> None:
        """Close connection to the remote server.

        Must be implemented by subclasses. Should close sockets and
        clean up resources. Must be safe to call multiple times.
        """
        ...

    @abstractmethod
    def _send_data(self, data: bytes) -> None:
        """Send raw RTCM data to the remote server.

        Must be implemented by subclasses. Should send the data
        over the established connection.

        Args:
            data: Raw bytes to send

        Raises:
            OSError: If send fails (triggers reconnection)
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Public accessor for connection status."""
        return self._is_connected()

    @abstractmethod
    def _is_connected(self) -> bool:
        """Check if the connection to the remote server is alive.

        Must be implemented by subclasses.

        Returns:
            True if connected and ready to send data
        """
        ...

    @abstractmethod
    def get_connection_info(self) -> dict[str, Any]:
        """Get connection information for logging and diagnostics.

        Must be implemented by subclasses.

        Returns:
            Dictionary containing connection details specific to the
            destination type
        """
        ...

    # --- String representations ---

    def __str__(self) -> str:
        """String representation of destination."""
        status = "running" if self._running else "stopped"
        connected = "connected" if self._is_connected() else "disconnected"
        return (
            f"{self.destination_type}:{self.name} "
            f"[{status}, {connected}, queue={self.queue_depth}]"
        )

    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"{self.__class__.__name__}("
            f"name='{self.name}', "
            f"type='{self.destination_type}', "
            f"running={self._running}, "
            f"filter={self.message_filter.mode.value}, "
            f"stats={self.stats})"
        )
