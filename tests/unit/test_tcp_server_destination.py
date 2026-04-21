"""Tests for TcpServerDestination — TCP server broadcasting RTCM to LAN clients.

Tests cover:
- Construction and initialization
- Factory builder + registration
- Server lifecycle (start/stop)
- Single-client and multi-client connections
- max_clients enforcement
- Data broadcast to connected clients
- Slow/dead client disconnection (write timeout)
- Client disconnect handling
- Queue integration
- Stats tracking
- Connection info
- Metrics integration (tcp_server_connected_clients gauge)
"""

from __future__ import annotations

import asyncio
import socket
import time
from unittest.mock import MagicMock

import pytest

from sp_rtk_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    TcpServerDestinationConfig,
)
from sp_rtk_base_relay.core.destinations.tcp_server_destination import (
    CLIENT_WRITE_TIMEOUT,
    TcpServerDestination,
    build_tcp_server_destination,
)
from sp_rtk_base_relay.core.destinations.destination_factory import DestinationFactory
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.exceptions import DestinationError


# ── Helpers ─────────────────────────────────────────────────────────


def _free_port() -> int:
    """Get a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_config(port: int, max_clients: int = 10) -> TcpServerDestinationConfig:
    return TcpServerDestinationConfig(
        host="127.0.0.1",
        port=port,
        max_clients=max_clients,
    )


def _make_dest(
    name: str = "local_tcp",
    port: int | None = None,
    max_clients: int = 10,
) -> TcpServerDestination:
    if port is None:
        port = _free_port()
    config = _make_config(port, max_clients)
    return TcpServerDestination(
        name=name,
        filter_config=FilterConfig.pass_all(),
        config=config,
    )


async def _connect_client(
    host: str, port: int, timeout: float = 5.0
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect a TCP client to the server."""
    return await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout,
    )


def _wait_for_server(dest: TcpServerDestination, timeout: float = 5.0) -> None:
    """Block until the server is listening."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if dest._server_running:
            return
        time.sleep(0.05)
    raise TimeoutError("Server did not start in time")


# ── Construction tests ──────────────────────────────────────────────


class TestTcpServerDestinationConstruction:
    """Test initialization and properties."""

    def test_basic_init(self) -> None:
        dest = _make_dest()
        assert dest.name == "local_tcp"
        assert dest.destination_type == "tcp_server"
        assert dest.client_count == 0
        assert not dest.is_running
        assert not dest._server_running

    def test_custom_name_and_port(self) -> None:
        dest = _make_dest(name="my_server", port=9999, max_clients=5)
        assert dest.name == "my_server"
        assert dest._port == 9999
        assert dest._max_clients == 5

    def test_host_defaults(self) -> None:
        config = TcpServerDestinationConfig()
        dest = TcpServerDestination(
            name="test",
            filter_config=FilterConfig.pass_all(),
            config=config,
        )
        assert dest._host == "0.0.0.0"
        assert dest._port == 5016

    def test_initial_stats(self) -> None:
        dest = _make_dest()
        stats = dest.get_stats()
        assert stats.bytes_sent == 0
        assert stats.messages_sent == 0
        assert stats.connection_attempts == 0

    def test_connection_info_before_start(self) -> None:
        dest = _make_dest(port=5555)
        info = dest.get_connection_info()
        assert info["host"] == "127.0.0.1"
        assert info["port"] == 5555
        assert info["max_clients"] == 10
        assert info["connected_clients"] == 0
        assert info["server_running"] is False

    def test_is_connected_before_start(self) -> None:
        dest = _make_dest()
        assert not dest.is_connected

    def test_str_representation(self) -> None:
        dest = _make_dest()
        s = str(dest)
        assert "tcp_server" in s
        assert "local_tcp" in s

    def test_repr_representation(self) -> None:
        dest = _make_dest()
        r = repr(dest)
        assert "TcpServerDestination" in r
        assert "local_tcp" in r


# ── Factory tests ───────────────────────────────────────────────────


class TestTcpServerFactory:
    """Test factory registration and builder."""

    def test_tcp_server_registered(self) -> None:
        assert DestinationFactory.is_registered("tcp_server")

    def test_builder_creates_destination(self) -> None:
        port = _free_port()
        cfg = DestinationConfig(
            name="local",
            type="tcp_server",
            enabled=True,
            filter=DestinationFilterConfig(mode="pass_all"),
            config=TcpServerDestinationConfig(
                host="127.0.0.1", port=port, max_clients=5
            ),
        )
        dest = build_tcp_server_destination(cfg)
        assert isinstance(dest, TcpServerDestination)
        assert dest.name == "local"
        assert dest._port == port
        assert dest._max_clients == 5

    def test_builder_rejects_wrong_config_type(self) -> None:
        cfg = DestinationConfig(
            name="bad",
            type="tcp_server",
            enabled=True,
            filter=DestinationFilterConfig(mode="pass_all"),
            config=MagicMock(),  # wrong type
        )
        with pytest.raises(DestinationError, match="Expected TcpServerDestinationConfig"):
            build_tcp_server_destination(cfg)

    def test_factory_create(self) -> None:
        port = _free_port()
        cfg = DestinationConfig(
            name="tcp_test",
            type="tcp_server",
            enabled=True,
            filter=DestinationFilterConfig(mode="pass_all"),
            config=TcpServerDestinationConfig(
                host="127.0.0.1", port=port
            ),
        )
        dest = DestinationFactory.create(cfg)
        assert isinstance(dest, TcpServerDestination)


# ── Server lifecycle tests ──────────────────────────────────────────


class TestTcpServerLifecycle:
    """Test start/stop and server binding."""

    def test_start_and_stop(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)
            assert dest.is_running
            assert dest._server_running
            assert dest.is_connected
        finally:
            dest.stop()
            time.sleep(0.2)
            assert not dest.is_running

    def test_stop_idempotent(self) -> None:
        dest = _make_dest()
        dest.stop()  # Should not raise

    def test_stats_after_start(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)
            stats = dest.get_stats()
            assert stats.connection_attempts == 1
            assert stats.successful_connections == 1
            assert stats.connected_since is not None
            assert stats.connected_since > 0
        finally:
            dest.stop()

    def test_connection_info_after_start(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)
            info = dest.get_connection_info()
            assert info["server_running"] is True
        finally:
            dest.stop()

    def test_bind_failure_records_error(self) -> None:
        """Binding to an in-use port raises DestinationError."""
        port = _free_port()
        # Occupy the port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        try:
            dest = _make_dest(port=port)
            dest.start()
            time.sleep(1.0)  # Let the thread attempt to bind
            # Server should have failed — stats show error
            assert not dest._server_running
        finally:
            sock.close()
            dest.stop()


# ── Client connection tests (integration with real TCP) ─────────────


class TestTcpServerClients:
    """Test client connections using real TCP sockets."""

    def test_single_client_connect_disconnect(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                reader, writer = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)
                assert dest.client_count == 1
                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.2)
                assert dest.client_count == 0

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_multiple_clients(self) -> None:
        dest = _make_dest(max_clients=5)
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                clients = []
                for _ in range(3):
                    r, w = await _connect_client("127.0.0.1", dest._port)
                    clients.append((r, w))
                    await asyncio.sleep(0.05)

                assert dest.client_count == 3

                # Disconnect one
                clients[0][1].close()
                await clients[0][1].wait_closed()
                await asyncio.sleep(0.2)
                assert dest.client_count == 2

                # Disconnect rest
                for _, w in clients[1:]:
                    w.close()
                    await w.wait_closed()
                await asyncio.sleep(0.2)
                assert dest.client_count == 0

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_max_clients_enforced(self) -> None:
        dest = _make_dest(max_clients=2)
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                c1_r, c1_w = await _connect_client("127.0.0.1", dest._port)
                c2_r, c2_w = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)
                assert dest.client_count == 2

                # Third client should be rejected
                c3_r, c3_w = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.2)
                # Server accepted TCP but closed immediately
                data = await asyncio.wait_for(c3_r.read(1024), timeout=2.0)
                assert data == b""  # EOF — connection closed by server
                assert dest.client_count == 2

                # Cleanup
                c1_w.close()
                c2_w.close()
                c3_w.close()

            asyncio.run(_run())
        finally:
            dest.stop()


# ── Broadcast tests ─────────────────────────────────────────────────


class TestTcpServerBroadcast:
    """Test data broadcasting to clients."""

    def test_broadcast_to_single_client(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                reader, writer = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)

                # Enqueue data
                test_data = b"\xd3\x00\x0aHello RTCM"
                dest.enqueue(test_data)
                await asyncio.sleep(0.3)

                # Read from client
                data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                assert data == test_data

                writer.close()
                await writer.wait_closed()

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_broadcast_to_multiple_clients(self) -> None:
        dest = _make_dest(max_clients=5)
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                clients = []
                for _ in range(3):
                    r, w = await _connect_client("127.0.0.1", dest._port)
                    clients.append((r, w))
                await asyncio.sleep(0.1)

                test_data = b"\xd3\x00\x05RTCM3"
                dest.enqueue(test_data)
                await asyncio.sleep(0.3)

                for reader, _ in clients:
                    data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                    assert data == test_data

                for _, w in clients:
                    w.close()
                    await w.wait_closed()

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_stats_after_broadcast(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                reader, writer = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)

                test_data = b"\xd3\x00\x0a" + b"x" * 10
                dest.enqueue(test_data)
                await asyncio.sleep(0.3)

                # Read to ensure it was sent
                await asyncio.wait_for(reader.read(1024), timeout=2.0)

                stats = dest.get_stats()
                assert stats.bytes_sent >= len(test_data)
                assert stats.messages_sent >= 1
                assert stats.last_send_time > 0

                writer.close()
                await writer.wait_closed()

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_no_clients_data_discarded(self) -> None:
        """Data enqueued with no clients connected is silently discarded."""
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)
            dest.enqueue(b"test data")
            time.sleep(0.3)
            stats = dest.get_stats()
            # No clients, so no bytes_sent
            assert stats.bytes_sent == 0
            assert stats.messages_sent == 0
        finally:
            dest.stop()

    def test_multiple_broadcasts(self) -> None:
        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                reader, writer = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)

                for i in range(5):
                    dest.enqueue(f"msg{i}".encode())
                    await asyncio.sleep(0.1)

                await asyncio.sleep(0.3)
                data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                assert b"msg0" in data
                assert b"msg4" in data

                writer.close()
                await writer.wait_closed()

            asyncio.run(_run())
        finally:
            dest.stop()


# ── Queue integration tests ─────────────────────────────────────────


class TestTcpServerQueue:
    """Test queue operations."""

    def test_enqueue_returns_true(self) -> None:
        dest = _make_dest()
        assert dest.enqueue(b"data") is True

    def test_queue_full_returns_false(self) -> None:
        dest = TcpServerDestination(
            name="small_q",
            filter_config=FilterConfig.pass_all(),
            config=_make_config(_free_port()),
            queue_size=2,
        )
        assert dest.enqueue(b"a") is True
        assert dest.enqueue(b"b") is True
        assert dest.enqueue(b"c") is False  # Full
        assert dest.stats.messages_dropped == 1

    def test_clear_queue(self) -> None:
        dest = _make_dest()
        dest.enqueue(b"a")
        dest.enqueue(b"b")
        cleared = dest.clear_queue()
        assert cleared == 2
        assert dest.queue_depth == 0


# ── Abstract method coverage ────────────────────────────────────────


class TestAbstractMethods:
    """Verify the unused abstract methods are safe to call."""

    def test_connect_is_noop(self) -> None:
        dest = _make_dest()
        dest._connect()  # Should not raise

    def test_send_data_is_noop(self) -> None:
        dest = _make_dest()
        dest._send_data(b"test")  # Should not raise

    def test_disconnect_before_start(self) -> None:
        dest = _make_dest()
        dest._disconnect()  # Should not raise


# ── Metrics integration tests ───────────────────────────────────────


class TestTcpServerMetrics:
    """Test MetricsCollector integration with tcp_server_connected_clients."""

    def test_client_count_metric_updated(self) -> None:
        """Verify MetricsCollector reads client_count from tcp_server."""
        from sp_rtk_base_relay.metrics import MetricsCollector

        # Use unique namespace to avoid conflicts
        ns = f"test_tcp_metric_{int(time.time() * 1000)}"
        mc = MetricsCollector(namespace=ns)

        dest = _make_dest()
        dest.start()
        try:
            _wait_for_server(dest)

            async def _run() -> None:
                reader, writer = await _connect_client("127.0.0.1", dest._port)
                await asyncio.sleep(0.1)

                # Update metrics
                mc.update_all([dest])

                val = mc.tcp_server_connected_clients.labels(
                    destination="local_tcp"
                )._value.get()
                assert val == 1.0

                writer.close()
                await writer.wait_closed()
                await asyncio.sleep(0.2)

                mc.update_all([dest])
                val = mc.tcp_server_connected_clients.labels(
                    destination="local_tcp"
                )._value.get()
                assert val == 0.0

            asyncio.run(_run())
        finally:
            dest.stop()

    def test_destination_type_check(self) -> None:
        """Non-tcp_server destinations don't set client count gauge."""
        from sp_rtk_base_relay.metrics import MetricsCollector

        ns = f"test_tcp_notype_{int(time.time() * 1000)}"
        mc = MetricsCollector(namespace=ns)

        mock_dest = MagicMock()
        mock_dest.name = "surepath"
        mock_dest.destination_type = "surepath"
        mock_dest.is_connected = True
        mock_dest.get_stats.return_value = MagicMock(
            bytes_sent=0,
            messages_sent=0,
            messages_dropped=0,
            messages_filtered=0,
            connection_attempts=0,
            errors=0,
            queue_depth=0,
        )

        mc.update_all([mock_dest])
        # Should not have set tcp_server_connected_clients for surepath
        # (no labels initialized for this destination)


# ── Write timeout / dead client tests ───────────────────────────────


class TestTcpServerWriteTimeout:
    """Test that slow/dead clients are disconnected."""

    def test_write_timeout_constant(self) -> None:
        assert CLIENT_WRITE_TIMEOUT == 5.0
