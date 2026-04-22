"""Integration tests: NtripDestination ↔ MockNtripCaster.

Tests real TCP connections on localhost — no mocked sockets.
Validates the full NTRIP v1.0 and v2.0 protocol handshakes,
data streaming (raw and chunked), auth rejection, caster crashes,
and data integrity across multiple RTCM frames.
"""

from __future__ import annotations

import time

import pytest

from sp_rtk_base_relay.config import NtripDestinationConfig
from sp_rtk_base_relay.core.destinations.ntrip_destination import NtripDestination
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.exceptions import NtripError
from tests.fixtures.mock_ntrip_caster import MockNtripCaster

# ======================================================================
# Helpers
# ======================================================================

PASSWORD = "test_secret"
MOUNTPOINT = "TEST_MOUNT"
RTCM_PAYLOAD = b"\xd3\x00\x0d" + b"\x41" * 13 + b"\x00\x00\x00"  # Fake RTCM frame


def _make_config(
    port: int,
    version: str = "2.0",
    password: str = PASSWORD,
) -> NtripDestinationConfig:
    """Create an NtripDestinationConfig pointing at localhost."""
    return NtripDestinationConfig(
        caster="127.0.0.1",
        port=port,
        mountpoint=MOUNTPOINT,
        password=password,
        username="admin",
        version=version,
        connection_timeout=5,
        retry_initial_delay=1,
        retry_max_delay=10,
        retry_multiplier=2.0,
    )


def _make_destination(
    port: int,
    version: str = "2.0",
    password: str = PASSWORD,
    name: str = "test-ntrip",
) -> NtripDestination:
    """Create an NtripDestination targeting localhost:port."""
    cfg = _make_config(port, version=version, password=password)
    return NtripDestination(
        name=name,
        filter_config=FilterConfig.pass_all(),
        ntrip_config=cfg,
    )


# ======================================================================
# v1.0 Protocol Tests
# ======================================================================


class TestNtripV1Integration:
    """NTRIP v1.0 (SOURCE + raw binary) integration tests."""

    def test_v1_connect_and_send(self) -> None:
        """Connect via v1.0, send RTCM data, verify caster receives it raw."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="1.0")
            dest._connect()
            assert dest._is_connected()

            caster.wait_for_connection(timeout=3.0)
            assert caster.detected_version == "1.0"

            dest._send_data(RTCM_PAYLOAD)
            time.sleep(0.3)

            received = caster.get_received_data()
            assert received == RTCM_PAYLOAD

            dest._disconnect()

    def test_v1_source_header_format(self) -> None:
        """Verify v1.0 SOURCE request contains password and mountpoint."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="1.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            assert f"SOURCE {PASSWORD}" in caster.request_headers
            assert f"/{MOUNTPOINT}" in caster.request_headers
            assert "Source-Agent:" in caster.request_headers

            dest._disconnect()

    def test_v1_raw_data_no_chunking(self) -> None:
        """v1.0 data is sent raw — no chunked encoding wrapping."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="1.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            raw_data = b"\x01\x02\x03\x04\x05"
            dest._send_data(raw_data)
            time.sleep(0.3)

            assert caster.get_received_data() == raw_data
            dest._disconnect()

    def test_v1_auth_rejected(self) -> None:
        """Caster rejects v1.0 auth with wrong password → NtripError."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(
                caster.port, version="1.0", password="wrong_password"
            )
            with pytest.raises(NtripError, match="auth failed"):
                dest._connect()

    def test_v1_multiple_frames(self) -> None:
        """Send multiple RTCM frames, verify all arrive in order."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="1.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            frames = [bytes([i] * 20) for i in range(5)]
            for frame in frames:
                dest._send_data(frame)

            time.sleep(0.5)

            received = caster.get_received_data()
            expected = b"".join(frames)
            assert received == expected

            dest._disconnect()


# ======================================================================
# v2.0 Protocol Tests
# ======================================================================


class TestNtripV2Integration:
    """NTRIP v2.0 (HTTP POST + chunked) integration tests."""

    def test_v2_connect_and_send(self) -> None:
        """Connect via v2.0, send RTCM data, verify caster decodes chunks."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            assert dest._is_connected()

            caster.wait_for_connection(timeout=3.0)
            assert caster.detected_version == "2.0"

            dest._send_data(RTCM_PAYLOAD)
            time.sleep(0.3)

            received = caster.get_received_data()
            assert received == RTCM_PAYLOAD

            dest._disconnect()

    def test_v2_post_header_format(self) -> None:
        """Verify v2.0 POST request has correct headers."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            headers = caster.request_headers
            assert f"POST /{MOUNTPOINT} HTTP/1.1" in headers
            assert "Ntrip-Version: Ntrip/2.0" in headers
            assert "Authorization: Basic" in headers
            assert "Transfer-Encoding: chunked" in headers
            assert "User-Agent:" in headers

            dest._disconnect()

    def test_v2_chunked_encoding_roundtrip(self) -> None:
        """v2.0 data is chunked — caster decodes back to original."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            original = bytes(range(256))
            dest._send_data(original)
            time.sleep(0.3)

            assert caster.get_received_data() == original
            dest._disconnect()

    def test_v2_auth_rejected(self) -> None:
        """Caster rejects v2.0 auth → NtripError."""
        with MockNtripCaster(port=0, password=PASSWORD, accept_auth=False) as caster:
            dest = _make_destination(caster.port, version="2.0")
            with pytest.raises(NtripError, match="auth failed"):
                dest._connect()

    def test_v2_multiple_frames(self) -> None:
        """Send multiple frames via chunked encoding, all arrive intact."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            frames = [bytes([i] * 30) for i in range(5)]
            for frame in frames:
                dest._send_data(frame)

            time.sleep(0.5)

            received = caster.get_received_data()
            expected = b"".join(frames)
            assert received == expected

            dest._disconnect()


# ======================================================================
# Error & Edge-Case Tests
# ======================================================================


class TestNtripErrorScenarios:
    """Error handling: caster crashes, connection refused, etc."""

    def test_connection_refused(self) -> None:
        """Connecting to a non-listening port raises NtripError."""
        dest = _make_destination(port=19999, version="2.0")
        with pytest.raises(NtripError, match="connection failed"):
            dest._connect()

    def test_caster_disconnect_detected(self) -> None:
        """When caster closes, next send() raises OSError."""
        with MockNtripCaster(
            port=0, password=PASSWORD, disconnect_after_bytes=10
        ) as caster:
            dest = _make_destination(caster.port, version="1.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            # Send enough to trigger caster disconnect
            dest._send_data(b"\x00" * 50)
            time.sleep(0.5)

            # After caster disconnects, next send should fail
            with pytest.raises(OSError):
                for _ in range(100):
                    dest._send_data(b"\x00" * 100)
                    time.sleep(0.01)

            dest._disconnect()

    def test_disconnect_idempotent(self) -> None:
        """Calling _disconnect() when already disconnected is safe."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            dest._disconnect()
            assert not dest._is_connected()

            # Second disconnect is safe
            dest._disconnect()
            assert not dest._is_connected()

    def test_send_without_connect_raises(self) -> None:
        """Sending data without connecting raises OSError."""
        dest = _make_destination(port=19998, version="1.0")
        with pytest.raises(OSError, match="socket is None"):
            dest._send_data(b"test")


# ======================================================================
# Connection Info Tests
# ======================================================================


class TestNtripConnectionInfo:
    """Connection info / diagnostics."""

    def test_connection_info_connected(self) -> None:
        """get_connection_info() reflects connected state."""
        with MockNtripCaster(port=0, password=PASSWORD) as caster:
            dest = _make_destination(caster.port, version="2.0")
            dest._connect()
            caster.wait_for_connection(timeout=3.0)

            info = dest.get_connection_info()
            assert info["connected"] is True
            assert info["type"] == "ntrip"
            assert info["mountpoint"] == MOUNTPOINT
            assert info["version"] == "2.0"
            assert info["caster"] == "127.0.0.1"

            dest._disconnect()

    def test_connection_info_disconnected(self) -> None:
        """get_connection_info() reflects disconnected state."""
        dest = _make_destination(port=19997, version="1.0")
        info = dest.get_connection_info()
        assert info["connected"] is False


# ======================================================================
# MockNtripCaster self-tests
# ======================================================================


class TestMockCasterSelfTest:
    """Verify MockNtripCaster fixture works correctly in isolation."""

    def test_caster_starts_and_stops(self) -> None:
        """Caster starts on ephemeral port and stops cleanly."""
        with MockNtripCaster(port=0) as caster:
            assert caster.port > 0
            assert caster.connection_count == 0

    def test_decode_chunks_simple(self) -> None:
        """Chunked encoding decoder handles a single chunk."""
        raw = b"5\r\nhello\r\n"
        result = MockNtripCaster._decode_chunks(raw)
        assert result == b"hello"

    def test_decode_chunks_multiple(self) -> None:
        """Chunked encoding decoder handles multiple chunks."""
        raw = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        result = MockNtripCaster._decode_chunks(raw)
        assert result == b"hello world"

    def test_decode_chunks_empty(self) -> None:
        """Chunked encoding decoder handles zero-length terminator."""
        raw = b"0\r\n\r\n"
        result = MockNtripCaster._decode_chunks(raw)
        assert result == b""
