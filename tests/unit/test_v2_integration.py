"""v2 Multi-Destination Integration Tests.

Tests the full v2 fan-out path with real TCP sockets:
  MockInput → BroadcastHub → [NTRIP casters, TCP server]

No hardware required — all localhost with ephemeral ports.

Note: NtripDestination uses *lazy connect* — the socket is only opened
when the first piece of data arrives in the queue. Tests must therefore
feed data **before** waiting for `caster.wait_for_connection()`.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

from sp_rtk_base_relay.config import (
    NtripDestinationConfig,
    TcpServerDestinationConfig,
)
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.destinations.ntrip_destination import NtripDestination
from sp_rtk_base_relay.core.destinations.tcp_server_destination import (
    TcpServerDestination,
)
from sp_rtk_base_relay.core.input_sources.base_input import InputSource
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.metrics import MetricsCollector
from tests.fixtures.mock_ntrip_caster import MockNtripCaster
from tests.fixtures.rtcm_generator import RTCMGenerator

# ======================================================================
# Helpers
# ======================================================================

PASSWORD = "v2_integration_test"
MOUNTPOINT = "V2_TEST"


class FeedInputSource(InputSource):
    """Minimal input source that serves pre-loaded data chunks.

    Feeds one chunk per read_data() call, then returns None.
    Thread-safe via a simple list pop.
    """

    def __init__(self) -> None:
        super().__init__("FeedInput")
        self._chunks: list[bytes] = []
        self._lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        """Enqueue a data chunk."""
        with self._lock:
            self._chunks.append(data)

    def connect(self) -> bool:
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        with self._lock:
            if self._chunks:
                chunk = self._chunks.pop(0)
                self._update_read_stats(chunk)
                return chunk
        # Sleep briefly to avoid busy-loop in BroadcastHub
        time.sleep(0.05)
        return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "feed"}


def _make_ntrip_dest(
    port: int,
    version: str = "2.0",
    name: str = "test-ntrip",
    filter_config: FilterConfig | None = None,
) -> NtripDestination:
    """Create an NtripDestination targeting localhost:port."""
    cfg = NtripDestinationConfig(
        caster="127.0.0.1",
        port=port,
        mountpoint=MOUNTPOINT,
        password=PASSWORD,
        username="admin",
        version=version,
        connection_timeout=5,
        retry_initial_delay=1,
        retry_max_delay=10,
        retry_multiplier=2.0,
    )
    return NtripDestination(
        name=name,
        filter_config=filter_config or FilterConfig.pass_all(),
        ntrip_config=cfg,
    )


def _free_port() -> int:
    """Get an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_tcp_server_dest(
    port: int | None = None,
    name: str = "test-tcp-srv",
    filter_config: FilterConfig | None = None,
) -> TcpServerDestination:
    """Create a TcpServerDestination on localhost with a known port."""
    if port is None:
        port = _free_port()
    cfg = TcpServerDestinationConfig(host="127.0.0.1", port=port, max_clients=5)
    return TcpServerDestination(
        name=name,
        filter_config=filter_config or FilterConfig.pass_all(),
        config=cfg,
    )


def _build_rtcm_frame(msg_type: int = 1077, payload_size: int = 20) -> bytes:
    """Build a valid RTCM frame using RTCMGenerator."""
    gen = RTCMGenerator()
    return gen.generate_rtcm_message(message_type=msg_type, size=payload_size)


# ======================================================================
# BroadcastHub → NTRIP Caster
# ======================================================================


class TestBroadcastToNtrip:
    """Feed data through BroadcastHub into real NTRIP casters."""

    def test_hub_to_single_ntrip_v2(self) -> None:
        """BroadcastHub feeds data → NtripDestination → MockNtripCaster (v2.0)."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            dest = _make_ntrip_dest(caster.port, version="2.0", name="ntrip-v2")

            hub = BroadcastHub(input_source=feed, destinations=[dest])
            feed.connect()
            hub.start()

            try:
                # Feed data — triggers lazy connect
                payload = _build_rtcm_frame(1077, 30)
                feed.feed(payload)

                # Now wait for the caster to see the connection
                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.0)

                received = caster.get_received_data()
                assert len(received) > 0, "Caster should have received data"
                assert payload in received or received == payload
            finally:
                hub.stop()

    def test_hub_to_single_ntrip_v1(self) -> None:
        """BroadcastHub feeds data → NtripDestination → MockNtripCaster (v1.0)."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            dest = _make_ntrip_dest(caster.port, version="1.0", name="ntrip-v1")

            hub = BroadcastHub(input_source=feed, destinations=[dest])
            feed.connect()
            hub.start()

            try:
                # Feed data — triggers lazy connect
                payload = _build_rtcm_frame(1087, 25)
                feed.feed(payload)

                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.0)

                received = caster.get_received_data()
                assert len(received) > 0
                assert received == payload
            finally:
                hub.stop()

    def test_hub_to_dual_ntrip_casters(self) -> None:
        """BroadcastHub fans out to two NTRIP casters simultaneously."""
        with (
            MockNtripCaster(port=0, password=PASSWORD) as c1,
            MockNtripCaster(port=0, password=PASSWORD) as c2,
        ):
            feed = FeedInputSource()
            d1 = _make_ntrip_dest(c1.port, version="2.0", name="caster-a")
            d2 = _make_ntrip_dest(c2.port, version="1.0", name="caster-b")

            hub = BroadcastHub(input_source=feed, destinations=[d1, d2])
            feed.connect()
            hub.start()

            try:
                # Feed data — triggers lazy connect on both
                payload = _build_rtcm_frame(1097, 40)
                feed.feed(payload)

                assert c1.wait_for_connection(timeout=5.0), "Caster A never connected"
                assert c2.wait_for_connection(timeout=5.0), "Caster B never connected"
                time.sleep(1.5)

                r1 = c1.get_received_data()
                r2 = c2.get_received_data()
                assert len(r1) > 0, "Caster A should receive data"
                assert len(r2) > 0, "Caster B should receive data"
                # v1.0 receives raw
                assert r2 == payload
            finally:
                hub.stop()

    def test_hub_multiple_frames(self) -> None:
        """Multiple RTCM frames arrive at the NTRIP caster in order."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            dest = _make_ntrip_dest(caster.port, version="1.0", name="multi-frame")

            hub = BroadcastHub(input_source=feed, destinations=[dest])
            feed.connect()
            hub.start()

            try:
                frames = [_build_rtcm_frame(1005 + i, 20 + i) for i in range(5)]
                # Feed all frames as one blob (realistic — input reads may batch)
                feed.feed(b"".join(frames))

                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.5)

                received = caster.get_received_data()
                expected = b"".join(frames)
                assert received == expected
            finally:
                hub.stop()


# ======================================================================
# BroadcastHub → TCP Server Destination
# ======================================================================


class TestBroadcastToTcpServer:
    """Feed data through BroadcastHub into TcpServerDestination, read via TCP client."""

    def test_hub_to_tcp_server_single_client(self) -> None:
        """BroadcastHub → TcpServerDestination → one TCP client receives data."""
        feed = FeedInputSource()
        dest = _make_tcp_server_dest(name="tcp-srv-1")

        hub = BroadcastHub(input_source=feed, destinations=[dest])
        feed.connect()
        hub.start()

        try:
            # Wait for TCP server to start
            time.sleep(1.0)
            server_port: int = dest._port  # type: ignore[attr-defined]
            assert server_port > 0, "TCP server should be listening"

            # Connect a client
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(("127.0.0.1", server_port))

            # Feed data
            payload = _build_rtcm_frame(1077, 30)
            feed.feed(payload)
            time.sleep(1.0)

            # Read from client
            data = bytearray()
            try:
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        break
                    data.extend(chunk)
            except TimeoutError:
                pass

            client.close()
            assert len(data) > 0, "TCP client should receive data"
            assert bytes(data) == payload
        finally:
            hub.stop()

    def test_hub_to_tcp_server_multiple_clients(self) -> None:
        """Multiple TCP clients all receive the same broadcast data."""
        feed = FeedInputSource()
        dest = _make_tcp_server_dest(name="tcp-srv-multi")

        hub = BroadcastHub(input_source=feed, destinations=[dest])
        feed.connect()
        hub.start()

        try:
            time.sleep(1.0)
            server_port: int = dest._port  # type: ignore[attr-defined]
            assert server_port > 0

            # Connect two clients
            clients: list[socket.socket] = []
            for _ in range(2):
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.settimeout(3.0)
                c.connect(("127.0.0.1", server_port))
                clients.append(c)

            time.sleep(0.3)

            # Feed data
            payload = _build_rtcm_frame(1087, 25)
            feed.feed(payload)
            time.sleep(1.0)

            # Both should receive data
            for i, c in enumerate(clients):
                data = bytearray()
                try:
                    while True:
                        chunk = c.recv(4096)
                        if not chunk:
                            break
                        data.extend(chunk)
                except TimeoutError:
                    pass
                c.close()
                assert len(data) > 0, f"Client {i} should receive data"
                assert bytes(data) == payload
        finally:
            hub.stop()

    def test_tcp_client_disconnect_no_effect(self) -> None:
        """A TCP client disconnecting does not affect the hub or other destinations."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            ntrip_dest = _make_ntrip_dest(caster.port, version="1.0", name="ntrip-ok")
            tcp_dest = _make_tcp_server_dest(name="tcp-srv-disc")

            hub = BroadcastHub(input_source=feed, destinations=[ntrip_dest, tcp_dest])
            feed.connect()
            hub.start()

            try:
                time.sleep(1.0)
                server_port: int = tcp_dest._port  # type: ignore[attr-defined]
                assert server_port > 0

                # Connect and immediately disconnect TCP client
                c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                c.settimeout(1.0)
                c.connect(("127.0.0.1", server_port))
                c.close()
                time.sleep(0.3)

                # Feed data — triggers lazy connect; NTRIP should still receive it
                payload = _build_rtcm_frame(1097, 20)
                feed.feed(payload)

                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.0)

                received = caster.get_received_data()
                assert len(received) > 0, "NTRIP dest should still receive data"
            finally:
                hub.stop()


# ======================================================================
# Multi-Destination Fan-Out
# ======================================================================


class TestMultiDestinationFanOut:
    """Test full fan-out: BroadcastHub → NTRIP + TCP Server simultaneously."""

    def test_fanout_ntrip_plus_tcp_server(self) -> None:
        """Both NTRIP caster and TCP client receive same data from BroadcastHub."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            ntrip_dest = _make_ntrip_dest(caster.port, version="1.0", name="ntrip-fan")
            tcp_dest = _make_tcp_server_dest(name="tcp-fan")

            hub = BroadcastHub(input_source=feed, destinations=[ntrip_dest, tcp_dest])
            feed.connect()
            hub.start()

            try:
                time.sleep(1.0)
                server_port: int = tcp_dest._port  # type: ignore[attr-defined]
                assert server_port > 0

                # Connect TCP client
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(3.0)
                client.connect(("127.0.0.1", server_port))
                time.sleep(0.3)

                # Feed data — triggers NTRIP lazy connect
                payload = _build_rtcm_frame(1077, 35)
                feed.feed(payload)

                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.5)

                # NTRIP caster should have it
                ntrip_data = caster.get_received_data()
                assert ntrip_data == payload, (
                    "NTRIP caster should receive exact payload"
                )

                # TCP client should have it
                tcp_data = bytearray()
                try:
                    while True:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        tcp_data.extend(chunk)
                except TimeoutError:
                    pass
                client.close()
                assert bytes(tcp_data) == payload, (
                    "TCP client should receive exact payload"
                )
            finally:
                hub.stop()

    def test_fault_isolation_caster_crash(self) -> None:
        """One NTRIP caster crashing doesn't affect TCP server destination."""
        with MockNtripCaster(
            port=0, password=PASSWORD, disconnect_after_bytes=10
        ) as crash_caster:
            feed = FeedInputSource()
            ntrip_dest = _make_ntrip_dest(
                crash_caster.port, version="1.0", name="ntrip-crash"
            )
            tcp_dest = _make_tcp_server_dest(name="tcp-survives")

            hub = BroadcastHub(input_source=feed, destinations=[ntrip_dest, tcp_dest])
            feed.connect()
            hub.start()

            try:
                time.sleep(1.0)
                server_port: int = tcp_dest._port  # type: ignore[attr-defined]
                assert server_port > 0

                # Connect TCP client
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(3.0)
                client.connect(("127.0.0.1", server_port))
                time.sleep(0.3)

                # Feed enough data to crash the NTRIP caster
                big_payload = _build_rtcm_frame(1077, 50)
                feed.feed(big_payload)

                crash_caster.wait_for_connection(timeout=5.0)
                time.sleep(1.5)

                # TCP client should still receive data
                tcp_data = bytearray()
                try:
                    while True:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        tcp_data.extend(chunk)
                except TimeoutError:
                    pass
                client.close()
                assert len(tcp_data) > 0, "TCP dest should survive caster crash"
            finally:
                hub.stop()

    def test_destination_stats_accumulate(self) -> None:
        """DestinationStats track correctly across fan-out."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            ntrip_dest = _make_ntrip_dest(
                caster.port, version="1.0", name="ntrip-stats"
            )

            hub = BroadcastHub(input_source=feed, destinations=[ntrip_dest])
            feed.connect()
            hub.start()

            try:
                # Feed first frame to trigger connection
                feed.feed(_build_rtcm_frame(1077, 20))
                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"

                # Feed 2 more frames
                for _ in range(2):
                    feed.feed(_build_rtcm_frame(1077, 20))
                    time.sleep(0.5)

                time.sleep(1.0)

                stats = ntrip_dest.get_stats()
                assert stats.messages_sent >= 3, (
                    f"Expected >=3 messages sent, got {stats.messages_sent}"
                )
                assert stats.bytes_sent > 0
            finally:
                hub.stop()


# ======================================================================
# Message Filtering Integration
# ======================================================================


class TestMessageFilteringIntegration:
    """Test per-destination message filtering through BroadcastHub."""

    def test_allowlist_filters_frames(self) -> None:
        """Allowlist filter only passes matching RTCM message types.

        When an allowlist filter is active the BroadcastHub parses RTCM
        frames and only forwards those that match. The caster should
        receive **less** data than the full blob that was fed.
        """
        with (
            MockNtripCaster(port=0, password=PASSWORD) as c_all,
            MockNtripCaster(port=0, password=PASSWORD) as c_filt,
        ):
            feed = FeedInputSource()
            # One pass_all, one allowlist — proves filtering happened
            d_all = _make_ntrip_dest(
                c_all.port,
                version="1.0",
                name="all-ref",
                filter_config=FilterConfig.pass_all(),
            )
            d_filt = _make_ntrip_dest(
                c_filt.port,
                version="1.0",
                name="filtered",
                filter_config=FilterConfig.allowlist([1077]),
            )

            hub = BroadcastHub(input_source=feed, destinations=[d_all, d_filt])
            feed.connect()
            hub.start()

            try:
                # Feed a 1077 frame and a 1087 frame — triggers lazy connect
                frame_1077 = _build_rtcm_frame(1077, 20)
                frame_1087 = _build_rtcm_frame(1087, 20)
                feed.feed(frame_1077 + frame_1087)

                assert c_all.wait_for_connection(timeout=5.0), (
                    "ref caster never connected"
                )
                assert c_filt.wait_for_connection(timeout=5.0), (
                    "filtered caster never connected"
                )
                time.sleep(1.5)

                all_data = c_all.get_received_data()
                filt_data = c_filt.get_received_data()

                # The filtered dest should receive less than pass_all
                assert len(all_data) > 0, "ref caster should receive data"
                assert len(filt_data) > 0, "filtered caster should receive some data"
                assert len(all_data) > len(filt_data), (
                    f"pass_all ({len(all_data)}B) should get more than "
                    f"filtered ({len(filt_data)}B)"
                )
            finally:
                hub.stop()

    def test_pass_all_vs_filtered_different_byte_counts(self) -> None:
        """pass_all dest gets more data than filtered dest."""
        with (
            MockNtripCaster(port=0, password=PASSWORD) as c_all,
            MockNtripCaster(port=0, password=PASSWORD) as c_filt,
        ):
            feed = FeedInputSource()

            d_all = _make_ntrip_dest(
                c_all.port,
                version="1.0",
                name="all",
                filter_config=FilterConfig.pass_all(),
            )
            d_filt = _make_ntrip_dest(
                c_filt.port,
                version="1.0",
                name="filt",
                filter_config=FilterConfig.allowlist([1077]),
            )

            hub = BroadcastHub(input_source=feed, destinations=[d_all, d_filt])
            feed.connect()
            hub.start()

            try:
                # Feed mixed frames — triggers lazy connect
                frames = (
                    _build_rtcm_frame(1077, 20)
                    + _build_rtcm_frame(1087, 20)
                    + _build_rtcm_frame(1097, 20)
                )
                feed.feed(frames)

                assert c_all.wait_for_connection(timeout=5.0), (
                    "pass_all caster never connected"
                )
                assert c_filt.wait_for_connection(timeout=5.0), (
                    "filtered caster never connected"
                )
                time.sleep(2.0)

                all_data = c_all.get_received_data()
                filt_data = c_filt.get_received_data()

                assert len(all_data) > 0, "pass_all caster should receive data"
                assert len(filt_data) > 0, "filtered caster should receive some data"
                assert len(all_data) > len(filt_data), (
                    f"pass_all ({len(all_data)}B) should receive more than "
                    f"filtered ({len(filt_data)}B)"
                )
            finally:
                hub.stop()

    def test_blocklist_drops_matching(self) -> None:
        """Blocklist filter drops matching types, passes others.

        Compare a pass_all dest with a blocklist dest to prove the
        blocklist receives fewer bytes.
        """
        with (
            MockNtripCaster(port=0, password=PASSWORD) as c_all,
            MockNtripCaster(port=0, password=PASSWORD) as c_blk,
        ):
            feed = FeedInputSource()
            d_all = _make_ntrip_dest(
                c_all.port,
                version="1.0",
                name="all-ref-blk",
                filter_config=FilterConfig.pass_all(),
            )
            d_blk = _make_ntrip_dest(
                c_blk.port,
                version="1.0",
                name="blocked",
                filter_config=FilterConfig.blocklist([1087]),
            )

            hub = BroadcastHub(input_source=feed, destinations=[d_all, d_blk])
            feed.connect()
            hub.start()

            try:
                frame_1077 = _build_rtcm_frame(1077, 20)
                frame_1087 = _build_rtcm_frame(1087, 20)
                feed.feed(frame_1077 + frame_1087)

                assert c_all.wait_for_connection(timeout=5.0), (
                    "ref caster never connected"
                )
                assert c_blk.wait_for_connection(timeout=5.0), (
                    "blocklist caster never connected"
                )
                time.sleep(1.5)

                all_data = c_all.get_received_data()
                blk_data = c_blk.get_received_data()

                assert len(all_data) > 0, "ref caster should receive data"
                assert len(blk_data) > 0, "blocklist caster should receive some data"
                assert len(all_data) > len(blk_data), (
                    f"pass_all ({len(all_data)}B) should get more than "
                    f"blocklist ({len(blk_data)}B)"
                )
            finally:
                hub.stop()


# ======================================================================
# Metrics Integration
# ======================================================================


class TestMetricsIntegration:
    """Verify MetricsCollector reads correct per-destination stats."""

    def test_metrics_update_from_live_destinations(self) -> None:
        """MetricsCollector.update_all() reads stats from live destinations."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            feed = FeedInputSource()
            dest = _make_ntrip_dest(caster.port, version="1.0", name="metrics-test")

            hub = BroadcastHub(input_source=feed, destinations=[dest])
            feed.connect()
            hub.start()

            try:
                # Feed data to trigger lazy connect
                feed.feed(_build_rtcm_frame(1077, 20))
                assert caster.wait_for_connection(timeout=5.0), "Caster never connected"
                time.sleep(1.0)

                # Create metrics collector and update — should not raise
                mc = MetricsCollector(namespace="test_v2_integ")
                mc.update_all(
                    destinations=[dest],
                    hub=hub,
                    input_connected=True,
                )

                # Verify destination stats show data was sent
                stats = dest.get_stats()
                assert stats.bytes_sent > 0, "Destination should have sent bytes"
                assert dest.is_connected, "Destination should be connected"

                # Second update should also succeed
                feed.feed(_build_rtcm_frame(1087, 20))
                time.sleep(1.0)
                mc.update_all(
                    destinations=[dest],
                    hub=hub,
                    input_connected=True,
                )

                # Hub should be running
                assert hub.is_running, "Hub should still be running"
            finally:
                hub.stop()
