"""RTCM client implementation for custom RTCM server connections.

This module provides the main RTCM client implementation with multi-threaded
architecture for handling TCP connections, authentication, heartbeat monitoring,
and data transmission to the custom RTCM server.
"""

import logging
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..config import RTCMServerConfig
from .connection_states import ConnectionState

logger = logging.getLogger(__name__)


@dataclass
class ConnectionStats:
    """Connection statistics and metrics."""

    connection_attempts: int = 0
    successful_connections: int = 0
    authentication_failures: int = 0
    heartbeat_timeouts: int = 0
    bytes_sent: int = 0
    messages_sent: int = 0
    last_heartbeat_time: float = 0.0
    connected_since: float | None = None
    current_retry_delay: int = 0


class HeartbeatMonitor:
    """Dedicated heartbeat monitoring for RTCM server connections.

    Runs in a separate daemon thread to monitor incoming $HB$ messages
    and detect connection timeouts.
    """

    def __init__(self, timeout_seconds: int = 30):
        """Initialize heartbeat monitor.

        Args:
            timeout_seconds: Heartbeat timeout in seconds
        """
        self.timeout_seconds = timeout_seconds
        self.last_heartbeat = 0.0
        self.running = False
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._timeout_callback: Callable[[], None] | None = None

    def start(
        self, socket_obj: socket.socket, timeout_callback: Callable[[], None]
    ) -> None:
        """Start heartbeat monitoring thread.

        Args:
            socket_obj: Connected socket to monitor
            timeout_callback: Callback function to call on timeout
        """
        if self.running:
            return

        self.socket = socket_obj
        self._timeout_callback = timeout_callback
        self.running = True

        self.thread = threading.Thread(
            target=self._monitor_loop, name="RTCMHeartbeatMonitor", daemon=True
        )
        self.thread.start()
        logger.debug("Heartbeat monitor started")

    def stop(self) -> None:
        """Stop heartbeat monitoring thread with guaranteed termination."""
        self.running = False

        # Clear socket reference to prevent lingering state
        self.socket = None  # type: ignore[assignment]

        if self.thread and self.thread.is_alive():
            # Don't try to join if we're calling from the same thread
            # (prevents "cannot join current thread" error)
            if threading.current_thread() != self.thread:
                thread_name = self.thread.name
                logger.debug(f"Waiting for {thread_name} to terminate")

                # Wait up to 5 seconds for thread to stop
                self.thread.join(timeout=5.0)

                # Verify thread actually stopped
                if self.thread.is_alive():
                    logger.error(
                        f"HeartbeatMonitor thread {thread_name} did not stop after 5 seconds - "
                        "this may cause socket issues"
                    )
                else:
                    logger.debug(
                        f"HeartbeatMonitor thread {thread_name} terminated successfully"
                    )

        logger.debug("Heartbeat monitor stopped")

    def update_heartbeat(self) -> None:
        """Update the last heartbeat timestamp."""
        with self._lock:
            self.last_heartbeat = time.time()
            logger.debug("Heartbeat updated")

    def time_since_heartbeat(self) -> float:
        """Get seconds since last heartbeat."""
        with self._lock:
            if self.last_heartbeat == 0:
                return 0.0
            return time.time() - self.last_heartbeat

    def is_timeout(self) -> bool:
        """Check if heartbeat has timed out."""
        return self.time_since_heartbeat() > self.timeout_seconds

    def _monitor_loop(self) -> None:
        """Main heartbeat monitoring loop."""
        buffer = b""

        try:
            while self.running:
                try:
                    # Check if socket is still valid
                    if self.socket is None:
                        break

                    # Set socket timeout for non-blocking reads
                    self.socket.settimeout(1.0)
                    data = self.socket.recv(4096)

                    if not data:
                        # Socket closed by server (expected every ~10 minutes)
                        logger.info(
                            "Socket closed by RTCM server during heartbeat monitoring"
                        )
                        if self._timeout_callback:
                            self._timeout_callback()
                        break

                    buffer += data

                    # Process all heartbeat messages in buffer
                    while b"$HB$" in buffer:
                        hb_index = buffer.find(b"$HB$")

                        # Remove everything up to and including the heartbeat
                        buffer = buffer[hb_index + 4 :]

                        # Update heartbeat timestamp
                        self.update_heartbeat()

                    # Check for heartbeat timeout
                    if self.is_timeout() and self.last_heartbeat > 0:
                        logger.info(
                            f"Heartbeat timeout after {self.time_since_heartbeat():.1f}s "
                            f"(threshold: {self.timeout_seconds}s)"
                        )
                        if self._timeout_callback:
                            self._timeout_callback()
                        break

                except TimeoutError:
                    # Check for timeout on each iteration
                    if self.is_timeout() and self.last_heartbeat > 0:
                        logger.info(
                            f"Heartbeat timeout after {self.time_since_heartbeat():.1f}s "
                            f"(threshold: {self.timeout_seconds}s)"
                        )
                        if self._timeout_callback:
                            self._timeout_callback()
                        break
                except Exception as e:
                    logger.error(f"Heartbeat monitoring error: {e}")
                    if self._timeout_callback:
                        self._timeout_callback()
                    break

        except Exception as e:
            logger.error(f"Critical heartbeat monitoring error: {e}")
            if self._timeout_callback:
                self._timeout_callback()


class RTCMClient:
    """RTCM client for custom server connections.

    Implements the complete RTCM client functionality including TCP connection
    management, custom authentication protocol, heartbeat monitoring, and
    data transmission with automatic reconnection.
    """

    def __init__(self, config: RTCMServerConfig):
        """Initialize RTCM client.

        Args:
            config: RTCM server configuration
        """
        self.config = config
        self.socket: socket.socket | None = None
        self.state = ConnectionState.DISCONNECTED
        self.stats = ConnectionStats()

        # Thread synchronization
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Heartbeat monitoring
        self.heartbeat_monitor = HeartbeatMonitor(config.heartbeat_timeout)

        # Retry logic
        self._current_retry_delay = config.retry_initial_delay
        self._last_connection_attempt = 0.0

        logger.info(f"RTCM client initialized for {config.host}:{config.port}")

    @property
    def connection_state(self) -> ConnectionState:
        """Get current connection state."""
        with self._lock:
            return self.state

    @property
    def is_connected(self) -> bool:
        """Check if client is connected and ready for data transmission."""
        return self.connection_state.can_send_data

    @property
    def connection_statistics(self) -> ConnectionStats:
        """Get connection statistics."""
        with self._lock:
            # Update real-time stats
            self.stats.current_retry_delay = self._current_retry_delay
            if self.heartbeat_monitor.last_heartbeat > 0:
                self.stats.last_heartbeat_time = self.heartbeat_monitor.last_heartbeat
            return self.stats

    def connect(self) -> bool:
        """Establish connection to RTCM server.

        Performs TCP connection and authentication in sequence.

        Returns:
            True if connection and authentication successful
        """
        with self._lock:
            if self.state in (
                ConnectionState.CONNECTING,
                ConnectionState.AUTHENTICATING,
            ):
                logger.debug("Connection attempt already in progress")
                return False

            self.state = ConnectionState.CONNECTING
            self.stats.connection_attempts += 1

        try:
            # Ensure any old socket is completely cleaned up first
            if self.socket is not None:
                logger.warning("Old socket exists during connect, forcing cleanup")
                self._cleanup_connection()
                time.sleep(0.2)  # Extra time for OS to release FD

            # Create and configure TCP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Set SO_REUSEADDR to allow quick reconnection to same address
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            self.socket.settimeout(self.config.connection_timeout)

            # Optimize socket for low latency
            try:
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError as e:
                logger.warning(f"Failed to set socket options: {e}")
                # Continue anyway, these are optimizations

            logger.info(
                f"Connecting to RTCM server {self.config.host}:{self.config.port}"
            )

            # Establish TCP connection
            try:
                self.socket.connect((self.config.host, self.config.port))
            except OSError as e:
                if e.errno == 9:  # EBADF - Bad file descriptor
                    logger.error(
                        f"Socket became invalid during connection (errno 9): {e}"
                    )
                else:
                    logger.error(f"Connection failed with OS error: {e}")
                raise

            # Set read timeout for authentication and data operations
            self.socket.settimeout(self.config.read_timeout)

            logger.info("TCP connection established, starting authentication")

            # Perform authentication
            if self._authenticate():
                with self._lock:
                    self.state = ConnectionState.CONNECTED
                    self.stats.successful_connections += 1
                    self.stats.connected_since = time.time()

                # Reset retry delay after successful connection
                self.reset_retry_delay()

                # Start heartbeat monitoring
                self.heartbeat_monitor.start(self.socket, self._on_heartbeat_timeout)

                logger.info("RTCM server connection established successfully")
                return True
            else:
                logger.error("RTCM server authentication failed")
                self._cleanup_connection()
                return False

        except TimeoutError:
            logger.error(f"Connection timeout after {self.config.connection_timeout}s")
            self._cleanup_connection()
            return False
        except socket.gaierror as e:
            logger.error(f"DNS resolution failed for {self.config.host}: {e}")
            self._cleanup_connection()
            return False
        except ConnectionRefusedError:
            logger.error(f"Connection refused by {self.config.host}:{self.config.port}")
            self._cleanup_connection()
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._cleanup_connection()
            return False

    def disconnect(self) -> None:
        """Disconnect from RTCM server and cleanup resources."""
        with self._lock:
            if self.state == ConnectionState.DISCONNECTED:
                return

            self.state = ConnectionState.STOPPING

        logger.info("Disconnecting from RTCM server")

        # Stop heartbeat monitoring
        self.heartbeat_monitor.stop()

        # Cleanup connection
        self._cleanup_connection()

        with self._lock:
            self.state = ConnectionState.DISCONNECTED
            self.stats.connected_since = None

        logger.info("Disconnected from RTCM server")

    def send_rtcm_data(self, data: bytes) -> bool:
        """Send RTCM data to server.

        Args:
            data: Raw RTCM message bytes

        Returns:
            True if data sent successfully
        """
        if not self.is_connected or not self.socket:
            logger.debug("Cannot send data: not connected")
            return False

        try:
            self.socket.sendall(data)

            # Update statistics
            with self._lock:
                self.stats.bytes_sent += len(data)
                self.stats.messages_sent += 1

            logger.debug(f"Sent {len(data)} bytes of RTCM data")
            return True

        except OSError as e:
            logger.error(f"Failed to send RTCM data: {e}")
            self._on_connection_lost()
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending RTCM data: {e}")
            return False

    def get_retry_delay(self) -> int:
        """Get the current retry delay for exponential backoff.

        Returns:
            Retry delay in seconds
        """
        return self._current_retry_delay

    def should_retry(self) -> bool:
        """Check if connection should be retried based on current state.

        Returns:
            True if connection should be retried
        """
        return self.connection_state.should_retry

    def _authenticate(self) -> bool:
        """Perform INIT authentication with RTCM server.

        Returns:
            True if authentication successful
        """
        if self.socket is None:
            logger.error("Cannot authenticate: socket not connected")
            return False

        with self._lock:
            self.state = ConnectionState.AUTHENTICATING

        try:
            # Create INIT command: INIT:username:password*
            init_command = f"INIT:{self.config.username}:{self.config.password}*"
            init_bytes = init_command.encode("ascii")

            logger.debug(f"Sending INIT command: INIT:{self.config.username}:***")

            # Send authentication command
            self.socket.sendall(init_bytes)

            # Wait for $HB$ response (authentication success)
            response = self.socket.recv(4)

            if response == b"$HB$":
                logger.info("Authentication successful, received $HB$ response")
                # Initialize heartbeat timestamp
                self.heartbeat_monitor.update_heartbeat()
                return True
            else:
                logger.error(f"Authentication failed, unexpected response: {response}")
                with self._lock:
                    self.stats.authentication_failures += 1
                return False

        except TimeoutError:
            logger.error(f"Authentication timeout after {self.config.read_timeout}s")
            with self._lock:
                self.stats.authentication_failures += 1
            return False
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            with self._lock:
                self.stats.authentication_failures += 1
            return False

    def _cleanup_connection(self) -> None:
        """Cleanup socket connection with aggressive OS-level release."""
        if self.socket:
            try:
                # Try to shutdown socket first (flushes buffers and signals disconnect)
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                    logger.debug("Socket shutdown completed")
                except OSError as e:
                    # Socket might already be disconnected - this is OK
                    logger.debug(
                        f"Socket shutdown failed (expected if already disconnected): {e}"
                    )

                # Now close the socket
                self.socket.close()
                logger.debug("Socket closed")

                # Small delay to let OS release file descriptor
                time.sleep(0.1)

            except Exception as e:
                # Log but continue - we need to clear the reference
                logger.warning(f"Error during socket cleanup: {e}")
            finally:
                self.socket = None
                logger.debug("Socket reference cleared")

        with self._lock:
            if self.state not in (
                ConnectionState.DISCONNECTED,
                ConnectionState.STOPPING,
            ):
                self.state = ConnectionState.ERROR

    def _on_heartbeat_timeout(self) -> None:
        """Handle heartbeat timeout detection."""
        logger.info("Heartbeat timeout detected")

        with self._lock:
            self.stats.heartbeat_timeouts += 1

        self._on_connection_lost()

    def _on_connection_lost(self) -> None:
        """Handle connection lost events."""
        logger.info("Connection lost, initiating cleanup")

        # Stop heartbeat monitoring
        self.heartbeat_monitor.stop()

        # Cleanup connection
        self._cleanup_connection()

        # Update retry delay for exponential backoff
        self._update_retry_delay()

        with self._lock:
            self.state = ConnectionState.DISCONNECTED
            self.stats.connected_since = None

    def reset_retry_delay(self) -> None:
        """Reset retry delay to initial value.

        This is typically called before reconnection attempts to ensure
        the initial configured delay is used rather than an exponentially
        backed-off value.
        """
        self._current_retry_delay = self.config.retry_initial_delay
        logger.debug("Retry delay reset to initial value")

    def _update_retry_delay(self) -> None:
        """Update retry delay using exponential backoff."""
        new_delay = min(
            int(self._current_retry_delay * self.config.retry_multiplier),
            self.config.retry_max_delay,
        )

        if new_delay != self._current_retry_delay:
            logger.info(
                f"Retry delay updated: {self._current_retry_delay}s -> {new_delay}s"
            )
            self._current_retry_delay = new_delay

        with self._lock:
            self.stats.current_retry_delay = self._current_retry_delay
