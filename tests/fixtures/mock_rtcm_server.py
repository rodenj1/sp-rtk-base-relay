"""Mock RTCM server for testing SP-Base-Relay connections.

This module provides a mock implementation of the custom RTCM server protocol
for automated testing of the RTCM client functionality.
"""

import socket
import threading
import time
import logging
from typing import Any
from dataclasses import dataclass, field


logger = logging.getLogger(__name__)


@dataclass
class MockServerStats:
    """Mock server connection statistics."""

    connections_accepted: int = 0
    authentication_attempts: int = 0
    successful_authentications: int = 0
    heartbeats_sent: int = 0
    rtcm_messages_received: int = 0
    bytes_received: int = 0
    active_connections: int = 0


@dataclass
class ClientConnection:
    """Represents an active client connection."""

    socket: socket.socket
    address: tuple[str, int]
    authenticated: bool = False
    connect_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    bytes_received: int = 0
    messages_received: int = 0


class MockRTCMServer:
    """Mock RTCM server implementing the custom authentication protocol.

    Provides a test server that mimics the behavior of the real RTCM server
    including authentication, heartbeat transmission, and data reception.
    """

    def __init__(
        self,
        port: int = 50010,
        bind_address: str = "127.0.0.1",
        heartbeat_interval: float = 1.0,
        valid_credentials: dict[str, str] | None = None,
    ):
        """Initialize mock RTCM server.

        Args:
            port: Port to bind server to
            bind_address: Address to bind server to
            heartbeat_interval: Interval between heartbeat messages in seconds
            valid_credentials: Dictionary of valid username:password pairs
        """
        self.port = port
        self.bind_address = bind_address
        self.heartbeat_interval = heartbeat_interval

        # Default test credentials
        self.valid_credentials = valid_credentials or {
            "your_mountpoint": "your_password",
            "testuser": "testpass",
            "user1": "pass1",
        }

        # Server state
        self.running = False
        self.server_socket: socket.socket | None = None
        self.accept_thread: threading.Thread | None = None
        self.clients: list[ClientConnection] = []
        self.stats = MockServerStats()

        # Thread synchronization
        self._lock = threading.Lock()
        self._client_threads: list[threading.Thread] = []

        logger.info(f"Mock RTCM server initialized on {bind_address}:{port}")

    def start(self) -> None:
        """Start the mock server."""
        if self.running:
            logger.warning("Server already running")
            return

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.bind_address, self.port))
            self.server_socket.listen(5)

            self.running = True

            # Start accept thread
            self.accept_thread = threading.Thread(
                target=self._accept_loop, name="MockRTCMServerAccept", daemon=True
            )
            self.accept_thread.start()

            logger.info(f"Mock RTCM server started on {self.bind_address}:{self.port}")

        except Exception as e:
            logger.error(f"Failed to start mock server: {e}")
            self.stop()
            raise

    def stop(self) -> None:
        """Stop the mock server and cleanup resources."""
        if not self.running:
            return

        logger.info("Stopping mock RTCM server")
        self.running = False

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        # Close all client connections
        with self._lock:
            for client in self.clients[
                :
            ]:  # Copy list to avoid modification during iteration
                self._close_client_connection(client)
            self.clients.clear()

        # Wait for threads to complete
        if self.accept_thread and self.accept_thread.is_alive():
            self.accept_thread.join(timeout=2.0)

        for thread in self._client_threads[:]:
            if thread.is_alive():
                thread.join(timeout=1.0)

        logger.info("Mock RTCM server stopped")

    def get_stats(self) -> MockServerStats:
        """Get server statistics."""
        with self._lock:
            self.stats.active_connections = len(self.clients)
            return self.stats

    def get_active_connections(self) -> list[ClientConnection]:
        """Get list of active client connections."""
        with self._lock:
            return self.clients.copy()

    def wait_for_connections(self, count: int, timeout: float = 5.0) -> bool:
        """Wait for specified number of active connections.

        Args:
            count: Number of connections to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            True if connection count reached within timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self._lock:
                if len(self.clients) >= count:
                    return True
            time.sleep(0.1)
        return False

    def _accept_loop(self) -> None:
        """Main server accept loop."""
        try:
            while self.running:
                try:
                    # Accept new client connection
                    if self.server_socket is None:
                        break
                    client_socket, client_address = self.server_socket.accept()

                    logger.debug(f"Accepted connection from {client_address}")

                    # Create client connection object
                    client = ClientConnection(
                        socket=client_socket, address=client_address
                    )

                    with self._lock:
                        self.clients.append(client)
                        self.stats.connections_accepted += 1

                    # Start client handler thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,),
                        name=f"MockRTCMClient-{client_address[0]}:{client_address[1]}",
                        daemon=True,
                    )
                    client_thread.start()

                    with self._lock:
                        self._client_threads.append(client_thread)

                except socket.error as e:
                    if self.running:
                        logger.error(f"Accept error: {e}")
                    break
                except Exception as e:
                    logger.error(f"Unexpected accept error: {e}")
                    break

        except Exception as e:
            logger.error(f"Critical accept loop error: {e}")

        logger.debug("Accept loop terminated")

    def _handle_client(self, client: ClientConnection) -> None:
        """Handle individual client connection.

        Args:
            client: Client connection to handle
        """
        try:
            logger.debug(f"Handling client {client.address}")

            # Set socket timeout
            client.socket.settimeout(30.0)

            # Wait for authentication
            if not self._handle_authentication(client):
                logger.warning(f"Authentication failed for {client.address}")
                self._close_client_connection(client)
                return

            # Start heartbeat sender
            heartbeat_thread = threading.Thread(
                target=self._send_heartbeats,
                args=(client,),
                name=f"MockHeartbeat-{client.address[0]}:{client.address[1]}",
                daemon=True,
            )
            heartbeat_thread.start()

            # Handle data reception
            self._handle_data_reception(client)

        except Exception as e:
            logger.error(f"Client handler error for {client.address}: {e}")
        finally:
            self._close_client_connection(client)

    def _handle_authentication(self, client: ClientConnection) -> bool:
        """Handle client authentication.

        Args:
            client: Client connection

        Returns:
            True if authentication successful
        """
        try:
            with self._lock:
                self.stats.authentication_attempts += 1

            # Read authentication data
            auth_data = client.socket.recv(1024)
            if not auth_data:
                return False

            # Parse INIT command
            auth_str = auth_data.decode("ascii", errors="ignore")
            logger.debug(f"Received authentication: {auth_str}")

            # Expected format: INIT:username:password*
            if not auth_str.startswith("INIT:") or not auth_str.endswith("*"):
                logger.warning(f"Invalid authentication format: {auth_str}")
                return False

            # Extract credentials
            auth_content = auth_str[5:-1]  # Remove 'INIT:' and '*'
            if ":" not in auth_content:
                logger.warning(f"Invalid credential format: {auth_content}")
                return False

            username, password = auth_content.split(":", 1)

            # Validate credentials
            if (
                username in self.valid_credentials
                and self.valid_credentials[username] == password
            ):
                logger.info(
                    f"Authentication successful for {username} from {client.address}"
                )

                # Send success response ($HB$)
                client.socket.sendall(b"$HB$")

                client.authenticated = True
                with self._lock:
                    self.stats.successful_authentications += 1

                return True
            else:
                logger.warning(
                    f"Invalid credentials: {username}:*** from {client.address}"
                )
                # Send no response for failed authentication (like real server)
                return False

        except Exception as e:
            logger.error(f"Authentication error for {client.address}: {e}")
            return False

    def _send_heartbeats(self, client: ClientConnection) -> None:
        """Send periodic heartbeat messages to client.

        Args:
            client: Client connection
        """
        try:
            while self.running and client.authenticated:
                try:
                    # Send heartbeat message
                    client.socket.sendall(b"$HB$")

                    with self._lock:
                        self.stats.heartbeats_sent += 1

                    logger.debug(f"Sent heartbeat to {client.address}")

                    # Wait for next heartbeat
                    time.sleep(self.heartbeat_interval)

                except socket.error as e:
                    logger.debug(f"Heartbeat send error for {client.address}: {e}")
                    break
                except Exception as e:
                    logger.error(f"Heartbeat error for {client.address}: {e}")
                    break

        except Exception as e:
            logger.error(f"Critical heartbeat error for {client.address}: {e}")

        logger.debug(f"Heartbeat sender stopped for {client.address}")

    def _handle_data_reception(self, client: ClientConnection) -> None:
        """Handle RTCM data reception from client.

        Args:
            client: Client connection
        """
        try:
            buffer = b""

            while self.running and client.authenticated:
                try:
                    # Receive data from client
                    data = client.socket.recv(4096)

                    if not data:
                        logger.debug(f"Client {client.address} closed connection")
                        break

                    buffer += data
                    client.last_activity = time.time()

                    # Update statistics
                    with self._lock:
                        client.bytes_received += len(data)
                        self.stats.bytes_received += len(data)

                    # Process RTCM messages (simple byte counting for mock)
                    # Real RTCM parser would identify message boundaries
                    if len(buffer) >= 10:  # Minimum RTCM message size
                        with self._lock:
                            client.messages_received += 1
                            self.stats.rtcm_messages_received += 1

                        logger.debug(
                            f"Received RTCM data from {client.address}: {len(data)} bytes"
                        )

                        # Reset buffer periodically to prevent memory growth
                        if len(buffer) > 8192:
                            buffer = buffer[-1024:]  # Keep last 1KB

                except socket.timeout:
                    # Timeout is normal, continue loop
                    continue
                except socket.error as e:
                    logger.debug(f"Data reception error for {client.address}: {e}")
                    break
                except Exception as e:
                    logger.error(f"Data handling error for {client.address}: {e}")
                    break

        except Exception as e:
            logger.error(f"Critical data reception error for {client.address}: {e}")

        logger.debug(f"Data reception stopped for {client.address}")

    def _close_client_connection(self, client: ClientConnection) -> None:
        """Close and cleanup client connection.

        Args:
            client: Client connection to close
        """
        try:
            # Close socket
            if client.socket:
                try:
                    client.socket.close()
                except Exception:
                    pass

            # Remove from clients list
            with self._lock:
                if client in self.clients:
                    self.clients.remove(client)
                    logger.debug(f"Removed client {client.address}")

        except Exception as e:
            logger.error(f"Error closing client {client.address}: {e}")


# Context manager support for easy testing
class MockRTCMServerContext:
    """Context manager for mock RTCM server.

    Provides automatic server startup and cleanup for testing.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize context manager with server parameters."""
        self.server = MockRTCMServer(**kwargs)

    def __enter__(self) -> MockRTCMServer:
        """Start server and return instance."""
        self.server.start()
        return self.server

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop server on context exit."""
        self.server.stop()


# Convenience function for testing
def create_test_server(
    port: int = 50011, **kwargs: Any  # Different port to avoid conflicts
) -> MockRTCMServerContext:
    """Create a mock RTCM server for testing.

    Args:
        port: Port to bind server to (default: 50011)
        **kwargs: Additional server parameters

    Returns:
        Context manager for mock server
    """
    return MockRTCMServerContext(port=port, **kwargs)
