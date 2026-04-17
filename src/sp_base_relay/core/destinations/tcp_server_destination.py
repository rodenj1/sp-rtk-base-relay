"""TCP server destination — broadcasts RTCM data to LAN clients.

This module implements a multi-client TCP server that accepts incoming
connections and broadcasts RTCM correction data to all connected clients.
Uses asyncio inside a dedicated thread (A+ pattern per architectural
decision #5).

Use case: Local rovers on the LAN can connect to this server to receive
real-time RTCM corrections without needing an internet-based NTRIP caster.

Design decisions:
- Asyncio event loop in the destination thread (A+ pattern)
- Per-client write timeout of 5 seconds (backpressure handling)
- max_clients enforcement — reject connections at the limit
- Client-count exposed via ``client_count`` property for metrics
"""

from __future__ import annotations

import asyncio
import logging
import queue
import time
from typing import Any

from sp_base_relay.config import DestinationConfig, TcpServerDestinationConfig
from sp_base_relay.core.destinations.base_destination import BaseDestination
from sp_base_relay.core.destinations.destination_factory import DestinationFactory
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.exceptions import DestinationError

logger = logging.getLogger(__name__)

# Per-client write timeout in seconds.  If a broadcast write to a client
# does not complete within this window the client is disconnected.
CLIENT_WRITE_TIMEOUT = 5.0


class TcpServerDestination(BaseDestination):
    """TCP server that broadcasts RTCM data to connected LAN clients.

    The server binds to ``host:port`` and accepts up to ``max_clients``
    simultaneous TCP connections.  Incoming RTCM data from the
    BroadcastHub queue is written to **all** connected clients.

    Internally an :mod:`asyncio` event loop runs in the destination
    thread (the "A+" pattern).  This cleanly handles many concurrent
    client connections without spawning additional threads.
    """

    def __init__(
        self,
        name: str,
        filter_config: FilterConfig,
        config: TcpServerDestinationConfig,
        *,
        queue_size: int = 100,
    ) -> None:
        super().__init__(
            name=name,
            destination_type="tcp_server",
            filter_config=filter_config,
            queue_size=queue_size,
        )
        self._host = config.host
        self._port = config.port
        self._max_clients = config.max_clients

        # Asyncio internals — created when the thread starts
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._server_running = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Return the number of currently connected clients."""
        return len(self._clients)

    # ------------------------------------------------------------------
    # BaseDestination abstract method implementations
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        """Not used — server lifecycle managed by ``_run_loop``."""

    def _disconnect(self) -> None:
        """Stop the asyncio server and disconnect all clients."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._server_running = False

    def _send_data(self, data: bytes) -> None:
        """Not used — broadcast handled by ``_broadcast_to_clients``."""

    def _is_connected(self) -> bool:
        """Return True when the TCP server is bound and listening."""
        return self._server_running

    def get_connection_info(self) -> dict[str, Any]:
        """Return server connection information for diagnostics."""
        return {
            "host": self._host,
            "port": self._port,
            "max_clients": self._max_clients,
            "connected_clients": self.client_count,
            "server_running": self._server_running,
        }

    # ------------------------------------------------------------------
    # Overridden run loop — asyncio inside thread
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Override the base run loop to run an asyncio event loop.

        This method is executed in the destination thread.  It creates
        a new asyncio event loop, starts the TCP server, and runs the
        broadcast loop until ``self._running`` is cleared.
        """
        logger.info(
            "Destination '%s' starting TCP server on %s:%d "
            "(max_clients=%d)",
            self.name,
            self._host,
            self._port,
            self._max_clients,
        )

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_run())
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = str(exc)
            logger.error(
                "Destination '%s' TCP server error: %s", self.name, exc
            )
        finally:
            # Clean up all remaining clients
            self._loop.run_until_complete(self._close_all_clients())
            if self._server is not None:
                self._server.close()
                self._loop.run_until_complete(self._server.wait_closed())
            self._loop.close()
            self._loop = None
            self._server = None
            self._server_running = False
            logger.info("Destination '%s' TCP server stopped", self.name)

    async def _async_run(self) -> None:
        """Main async entry point: start server + broadcast loop."""
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self._host,
                self._port,
            )
        except OSError as exc:
            raise DestinationError(
                f"Failed to bind TCP server on {self._host}:{self._port}: {exc}",
                destination_name=self.name,
            ) from exc

        self._server_running = True
        self.stats.connection_attempts += 1
        self.stats.successful_connections += 1
        self.stats.connected_since = time.time()

        addrs = [str(s.getsockname()) for s in self._server.sockets]
        logger.info(
            "Destination '%s' TCP server listening on %s",
            self.name,
            ", ".join(addrs),
        )

        # Run the broadcast loop — reads from queue and pushes to clients
        await self._broadcast_loop()

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new incoming client connection.

        Enforces ``max_clients``.  Once added, the coroutine waits
        until the client disconnects (EOF on the reader) so that the
        connection stays alive.
        """
        peer = writer.get_extra_info("peername")
        peer_str = f"{peer[0]}:{peer[1]}" if peer else "unknown"

        # Enforce max clients
        if len(self._clients) >= self._max_clients:
            logger.warning(
                "Destination '%s' rejecting client %s "
                "(max_clients=%d reached)",
                self.name,
                peer_str,
                self._max_clients,
            )
            writer.close()
            await writer.wait_closed()
            return

        self._clients.add(writer)
        logger.info(
            "Destination '%s' client connected: %s (%d/%d)",
            self.name,
            peer_str,
            len(self._clients),
            self._max_clients,
        )

        try:
            # Wait for client disconnect (reads until EOF)
            while self._running:
                data = await reader.read(1024)
                if not data:
                    break
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass
            logger.info(
                "Destination '%s' client disconnected: %s (%d/%d)",
                self.name,
                peer_str,
                len(self._clients),
                self._max_clients,
            )

    async def _close_all_clients(self) -> None:
        """Close all connected clients."""
        for writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass
        self._clients.clear()

    # ------------------------------------------------------------------
    # Broadcast loop
    # ------------------------------------------------------------------

    async def _broadcast_loop(self) -> None:
        """Read data from the queue and broadcast to all clients.

        Uses ``run_in_executor`` to read from the blocking
        :class:`queue.Queue` without stalling the event loop.
        """
        while self._running:
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, self._queue_get_with_timeout
                )
            except Exception:
                continue

            if data is None:
                # Poison pill or timeout
                if not self._running:
                    break
                continue

            if not self._clients:
                # No clients connected — discard silently
                continue

            await self._broadcast_to_clients(data)

    def _queue_get_with_timeout(self) -> bytes | None:
        """Blocking queue get with 1-second timeout.

        Called via ``run_in_executor`` to bridge blocking queue with
        the asyncio event loop.

        Returns:
            Data bytes, or None on timeout / poison pill.
        """
        try:
            return self._queue.get(timeout=1.0)
        except queue.Empty:
            return None

    async def _broadcast_to_clients(self, data: bytes) -> None:
        """Write *data* to all connected clients.

        Each client write has a :data:`CLIENT_WRITE_TIMEOUT` second
        timeout.  Clients that fail or time out are disconnected.
        """
        failed: list[asyncio.StreamWriter] = []

        for writer in list(self._clients):
            try:
                writer.write(data)
                await asyncio.wait_for(
                    writer.drain(), timeout=CLIENT_WRITE_TIMEOUT
                )
            except (
                asyncio.TimeoutError,
                ConnectionResetError,
                BrokenPipeError,
                OSError,
            ):
                failed.append(writer)

        # Remove failed clients
        for writer in failed:
            peer = writer.get_extra_info("peername")
            peer_str = f"{peer[0]}:{peer[1]}" if peer else "unknown"
            logger.warning(
                "Destination '%s' disconnecting slow/dead client %s",
                self.name,
                peer_str,
            )
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

        # Update stats — count bytes sent to all successful clients
        successful = len(self._clients)
        if successful > 0:
            self.stats.bytes_sent += len(data) * successful
            self.stats.messages_sent += successful
            self.stats.last_send_time = time.time()


# ------------------------------------------------------------------
# Factory builder + registration
# ------------------------------------------------------------------


def build_tcp_server_destination(config: DestinationConfig) -> BaseDestination:
    """Build a :class:`TcpServerDestination` from parsed config.

    Args:
        config: Destination configuration entry with type ``"tcp_server"``.

    Returns:
        Configured TcpServerDestination instance.

    Raises:
        DestinationError: If the config is invalid.
    """
    if not isinstance(config.config, TcpServerDestinationConfig):
        raise DestinationError(
            f"Expected TcpServerDestinationConfig, got {type(config.config).__name__}",
            destination_name=config.name,
        )

    filter_config = config.filter.to_filter_config()

    return TcpServerDestination(
        name=config.name,
        filter_config=filter_config,
        config=config.config,
    )


# Auto-register with the factory on module import
DestinationFactory.register("tcp_server", build_tcp_server_destination)
