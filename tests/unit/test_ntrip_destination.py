# pyright: reportPrivateUsage=false
"""Unit tests for NtripDestination — NTRIP v1.0 and v2.0 protocols."""

import base64
import socket
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from sp_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    NtripDestinationConfig,
    SurePathDestinationConfig,
)
from sp_base_relay.core.destinations.ntrip_destination import (
    NtripDestination,
    build_ntrip_destination,
)
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.exceptions import ConfigurationError, NtripError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ntrip_v1_config() -> NtripDestinationConfig:
    """Create NTRIP v1.0 config."""
    return NtripDestinationConfig(
        caster="rtk2go.com",
        port=2101,
        mountpoint="MY_MOUNT",
        password="my_password",
        username="",
        version="1.0",
        connection_timeout=10,
        retry_initial_delay=5,
        retry_max_delay=60,
        retry_multiplier=2.0,
    )


@pytest.fixture
def ntrip_v2_config() -> NtripDestinationConfig:
    """Create NTRIP v2.0 config."""
    return NtripDestinationConfig(
        caster="servers.onocoy.com",
        port=2101,
        mountpoint="ONOCOY_MOUNT",
        password="onocoy_pass",
        username="onocoy_user",
        version="2.0",
        connection_timeout=15,
        retry_initial_delay=10,
        retry_max_delay=120,
        retry_multiplier=2.0,
    )


@pytest.fixture
def filter_pass_all() -> FilterConfig:
    """Pass-all filter config."""
    return FilterConfig.pass_all()


@pytest.fixture
def dest_v1(
    ntrip_v1_config: NtripDestinationConfig, filter_pass_all: FilterConfig
) -> NtripDestination:
    """Create NTRIP v1.0 destination (not started)."""
    return NtripDestination(
        name="rtk2go",
        filter_config=filter_pass_all,
        ntrip_config=ntrip_v1_config,
    )


@pytest.fixture
def dest_v2(
    ntrip_v2_config: NtripDestinationConfig, filter_pass_all: FilterConfig
) -> NtripDestination:
    """Create NTRIP v2.0 destination (not started)."""
    return NtripDestination(
        name="onocoy",
        filter_config=filter_pass_all,
        ntrip_config=ntrip_v2_config,
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestNtripDestinationInit:
    """Tests for NtripDestination initialization."""

    def test_init_v1(self, dest_v1: NtripDestination) -> None:
        assert dest_v1.name == "rtk2go"
        assert dest_v1.destination_type == "ntrip"
        assert dest_v1._socket is None
        assert not dest_v1.is_connected
        assert dest_v1._config.version == "1.0"

    def test_init_v2(self, dest_v2: NtripDestination) -> None:
        assert dest_v2.name == "onocoy"
        assert dest_v2.destination_type == "ntrip"
        assert dest_v2._config.version == "2.0"

    def test_init_backoff_state(self, dest_v1: NtripDestination) -> None:
        assert dest_v1._retry_delay == 5.0
        assert dest_v1._next_connect_time == 0.0


# ---------------------------------------------------------------------------
# Connection (with mocked socket)
# ---------------------------------------------------------------------------


class TestNtripConnectionV1:
    """Tests for NTRIP v1.0 connection and auth."""

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v1_success(
        self, mock_socket_cls: Mock, dest_v1: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"ICY 200 OK\r\n"

        dest_v1._connect()

        assert dest_v1._socket is mock_sock
        mock_sock.connect.assert_called_once_with(("rtk2go.com", 2101))
        # Verify SOURCE request was sent
        sent_data = mock_sock.sendall.call_args_list[0][0][0]
        assert b"SOURCE my_password /MY_MOUNT" in sent_data
        assert b"Source-Agent:" in sent_data

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v1_auth_failure(
        self, mock_socket_cls: Mock, dest_v1: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"ERROR - Bad Password\r\n"

        with pytest.raises(NtripError, match="v1.0 auth failed"):
            dest_v1._connect()
        assert dest_v1._socket is None

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v1_connection_refused(
        self, mock_socket_cls: Mock, dest_v1: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.connect.side_effect = ConnectionRefusedError("Connection refused")

        with pytest.raises(NtripError, match="connection failed"):
            dest_v1._connect()
        assert dest_v1._socket is None


class TestNtripConnectionV2:
    """Tests for NTRIP v2.0 connection and auth."""

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v2_success(
        self, mock_socket_cls: Mock, dest_v2: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"HTTP/1.1 200 OK\r\n"

        dest_v2._connect()

        assert dest_v2._socket is mock_sock
        mock_sock.connect.assert_called_once_with(("servers.onocoy.com", 2101))
        # Verify HTTP POST request
        sent_data = mock_sock.sendall.call_args_list[0][0][0].decode("ascii")
        assert "POST /ONOCOY_MOUNT HTTP/1.1" in sent_data
        assert "Ntrip-Version: Ntrip/2.0" in sent_data
        assert "Transfer-Encoding: chunked" in sent_data
        # Verify Base64 credentials
        expected_creds = base64.b64encode(b"onocoy_user:onocoy_pass").decode()
        assert f"Authorization: Basic {expected_creds}" in sent_data

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v2_auth_failure(
        self, mock_socket_cls: Mock, dest_v2: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"HTTP/1.1 401 Unauthorized\r\n"

        with pytest.raises(NtripError, match="v2.0 auth failed"):
            dest_v2._connect()

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_v2_timeout(
        self, mock_socket_cls: Mock, dest_v2: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.side_effect = socket.timeout("timed out")

        with pytest.raises(NtripError, match="timeout"):
            dest_v2._connect()

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_connect_sets_keepalive(
        self, mock_socket_cls: Mock, dest_v2: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"HTTP/1.1 200 OK\r\n"

        dest_v2._connect()

        # Verify SO_KEEPALIVE was set
        keepalive_calls = [
            c for c in mock_sock.setsockopt.call_args_list
            if c[0][0] == socket.SOL_SOCKET and c[0][1] == socket.SO_KEEPALIVE
        ]
        assert len(keepalive_calls) == 1
        assert keepalive_calls[0][0][2] == 1


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


class TestNtripDisconnect:
    """Tests for disconnect behavior."""

    def test_disconnect_closes_socket(self, dest_v1: NtripDestination) -> None:
        mock_sock = MagicMock()
        dest_v1._socket = mock_sock

        dest_v1._disconnect()

        mock_sock.close.assert_called_once()
        assert dest_v1._socket is None
        assert dest_v1._next_connect_time == 0.0

    def test_disconnect_when_not_connected(self, dest_v1: NtripDestination) -> None:
        dest_v1._socket = None
        dest_v1._disconnect()  # Should not raise
        assert dest_v1._socket is None

    def test_disconnect_handles_socket_error(
        self, dest_v1: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_sock.close.side_effect = OSError("close error")
        dest_v1._socket = mock_sock

        dest_v1._disconnect()  # Should not raise
        assert dest_v1._socket is None


# ---------------------------------------------------------------------------
# Send data
# ---------------------------------------------------------------------------


class TestNtripSendData:
    """Tests for data sending (v1 raw vs v2 chunked)."""

    def test_send_data_v1_raw(self, dest_v1: NtripDestination) -> None:
        mock_sock = MagicMock()
        dest_v1._socket = mock_sock
        data = b"\xd3\x00\x0a" + b"\x00" * 10

        dest_v1._send_data(data)

        mock_sock.sendall.assert_called_once_with(data)

    def test_send_data_v2_chunked(self, dest_v2: NtripDestination) -> None:
        mock_sock = MagicMock()
        dest_v2._socket = mock_sock
        data = b"\xd3\x00\x0a" + b"\x00" * 10

        dest_v2._send_data(data)

        sent = mock_sock.sendall.call_args[0][0]
        # Should be: "d\r\n" + data + "\r\n" (13 bytes hex = "d")
        assert sent.startswith(f"{len(data):x}\r\n".encode())
        assert sent.endswith(b"\r\n")
        # Data should be embedded in the chunk
        assert data in sent

    def test_send_data_no_socket_raises(self, dest_v1: NtripDestination) -> None:
        dest_v1._socket = None
        with pytest.raises(OSError, match="socket is None"):
            dest_v1._send_data(b"test")

    def test_send_data_socket_error(self, dest_v1: NtripDestination) -> None:
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = BrokenPipeError("Broken pipe")
        dest_v1._socket = mock_sock

        with pytest.raises(BrokenPipeError):
            dest_v1._send_data(b"test")


# ---------------------------------------------------------------------------
# is_connected
# ---------------------------------------------------------------------------


class TestNtripIsConnected:
    """Tests for connection status check."""

    def test_connected_when_socket_exists(self, dest_v1: NtripDestination) -> None:
        dest_v1._socket = MagicMock()
        assert dest_v1._is_connected()
        assert dest_v1.is_connected

    def test_not_connected_when_no_socket(self, dest_v1: NtripDestination) -> None:
        dest_v1._socket = None
        assert not dest_v1._is_connected()
        assert not dest_v1.is_connected


# ---------------------------------------------------------------------------
# Connection info
# ---------------------------------------------------------------------------


class TestNtripConnectionInfo:
    """Tests for get_connection_info."""

    def test_connection_info_v1(self, dest_v1: NtripDestination) -> None:
        info = dest_v1.get_connection_info()
        assert info["name"] == "rtk2go"
        assert info["type"] == "ntrip"
        assert info["caster"] == "rtk2go.com"
        assert info["port"] == 2101
        assert info["mountpoint"] == "MY_MOUNT"
        assert info["version"] == "1.0"
        assert info["connected"] is False

    def test_connection_info_v2(self, dest_v2: NtripDestination) -> None:
        info = dest_v2.get_connection_info()
        assert info["version"] == "2.0"
        assert info["caster"] == "servers.onocoy.com"


# ---------------------------------------------------------------------------
# Backoff-aware reconnection
# ---------------------------------------------------------------------------


class TestNtripBackoff:
    """Tests for exponential backoff reconnection."""

    def test_attempt_connect_respects_backoff(
        self, dest_v1: NtripDestination
    ) -> None:
        dest_v1._next_connect_time = time.time() + 999
        with patch.object(dest_v1, "_connect") as mock_connect:
            dest_v1._attempt_connect()
            mock_connect.assert_not_called()

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_attempt_connect_success_resets_backoff(
        self, mock_socket_cls: Mock, dest_v1: NtripDestination
    ) -> None:
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"ICY 200 OK\r\n"
        dest_v1._retry_delay = 30.0  # Was in backoff

        dest_v1._attempt_connect()

        assert dest_v1._retry_delay == 5.0  # Reset to initial
        assert dest_v1._next_connect_time == 0.0

    def test_attempt_connect_failure_increases_backoff(
        self, dest_v1: NtripDestination
    ) -> None:
        with patch.object(
            dest_v1, "_connect", side_effect=NtripError("fail")
        ):
            dest_v1._attempt_connect()

        assert dest_v1._retry_delay == 10.0  # 5 * 2.0
        assert dest_v1._next_connect_time > time.time()

    def test_backoff_caps_at_max(self, dest_v1: NtripDestination) -> None:
        dest_v1._retry_delay = 50.0
        dest_v1._update_retry_delay()
        assert dest_v1._retry_delay == 60.0  # Capped at max

        dest_v1._retry_delay = 60.0
        dest_v1._update_retry_delay()
        assert dest_v1._retry_delay == 60.0  # Still capped

    def test_reset_retry_delay(self, dest_v1: NtripDestination) -> None:
        dest_v1._retry_delay = 30.0
        dest_v1._next_connect_time = time.time() + 100
        dest_v1.reset_retry_delay()
        assert dest_v1._retry_delay == 5.0
        assert dest_v1._next_connect_time == 0.0


# ---------------------------------------------------------------------------
# Read response helper
# ---------------------------------------------------------------------------


class TestReadResponse:
    """Tests for _read_response static method."""

    def test_reads_single_line(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b"ICY 200 OK\r\n"
        result = NtripDestination._read_response(mock_sock)
        assert "ICY 200 OK" in result

    def test_reads_multipart(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = [b"HTTP/1.1 ", b"200 OK\r\n"]
        result = NtripDestination._read_response(mock_sock)
        assert "200 OK" in result

    def test_timeout_raises_ntrip_error(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.side_effect = socket.timeout("timed out")
        with pytest.raises(NtripError, match="timeout"):
            NtripDestination._read_response(mock_sock, timeout=1.0)

    def test_empty_response(self) -> None:
        mock_sock = MagicMock()
        mock_sock.recv.return_value = b""
        result = NtripDestination._read_response(mock_sock)
        assert result == ""


# ---------------------------------------------------------------------------
# Factory builder
# ---------------------------------------------------------------------------


class TestBuildNtripDestination:
    """Tests for build_ntrip_destination factory function."""

    def test_build_success(self, ntrip_v2_config: NtripDestinationConfig) -> None:
        filter_cfg = DestinationFilterConfig(mode="pass_all")
        cfg = DestinationConfig(
            name="rtk2go",
            type="ntrip",
            enabled=True,
            filter=filter_cfg,
            config=ntrip_v2_config,
        )
        dest = build_ntrip_destination(cfg)
        assert isinstance(dest, NtripDestination)
        assert dest.name == "rtk2go"
        assert dest.destination_type == "ntrip"

    def test_build_wrong_config_type_raises(self) -> None:
        filter_cfg = DestinationFilterConfig(mode="pass_all")
        wrong_config = SurePathDestinationConfig(
            host="127.0.0.1", port=5000, username="u", password="p"
        )
        cfg = DestinationConfig(
            name="bad",
            type="ntrip",
            enabled=True,
            filter=filter_cfg,
            config=wrong_config,
        )
        with pytest.raises(ConfigurationError, match="Expected NtripDestinationConfig"):
            build_ntrip_destination(cfg)

    def test_factory_registration(self) -> None:
        """Verify 'ntrip' is registered in DestinationFactory."""
        from sp_base_relay.core.destinations.destination_factory import (
            DestinationFactory,
        )
        assert "ntrip" in DestinationFactory._builders


# ---------------------------------------------------------------------------
# Protocol format verification
# ---------------------------------------------------------------------------


class TestProtocolFormat:
    """Tests verifying exact protocol format compliance."""

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_v1_source_format(
        self, mock_socket_cls: Mock, dest_v1: NtripDestination
    ) -> None:
        """Verify v1 SOURCE request format matches NTRIP v1.0 spec."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"ICY 200 OK\r\n"

        dest_v1._connect()

        request = mock_sock.sendall.call_args_list[0][0][0].decode("ascii")
        lines = request.split("\r\n")
        assert lines[0] == "SOURCE my_password /MY_MOUNT"
        assert lines[1].startswith("Source-Agent: NTRIP sp-base-relay/")
        assert lines[2] == ""  # Empty line terminates headers

    @patch("sp_base_relay.core.destinations.ntrip_destination.socket.socket")
    def test_v2_post_format(
        self, mock_socket_cls: Mock, dest_v2: NtripDestination
    ) -> None:
        """Verify v2 HTTP POST format matches NTRIP v2.0 spec."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recv.return_value = b"HTTP/1.1 200 OK\r\n"

        dest_v2._connect()

        request = mock_sock.sendall.call_args_list[0][0][0].decode("ascii")
        lines = request.split("\r\n")
        assert lines[0] == "POST /ONOCOY_MOUNT HTTP/1.1"
        assert "Host: servers.onocoy.com" in lines
        assert "Ntrip-Version: Ntrip/2.0" in lines
        assert "Transfer-Encoding: chunked" in lines
        assert any("Authorization: Basic" in l for l in lines)
        assert lines[-1] == ""  # Empty line terminates headers

    def test_v2_chunked_encoding_format(
        self, dest_v2: NtripDestination
    ) -> None:
        """Verify chunked encoding follows HTTP spec: hex_len\\r\\ndata\\r\\n."""
        mock_sock = MagicMock()
        dest_v2._socket = mock_sock
        data = b"\xd3" + b"\x00" * 99  # 100 bytes

        dest_v2._send_data(data)

        sent = mock_sock.sendall.call_args[0][0]
        # 100 bytes hex = "64"
        assert sent == b"64\r\n" + data + b"\r\n"

    def test_v1_raw_send_no_framing(
        self, dest_v1: NtripDestination
    ) -> None:
        """Verify v1 sends raw bytes with no framing."""
        mock_sock = MagicMock()
        dest_v1._socket = mock_sock
        data = b"\xd3\x00\x0a" + b"\xff" * 10

        dest_v1._send_data(data)

        mock_sock.sendall.assert_called_once_with(data)


# ---------------------------------------------------------------------------
# String representations
# ---------------------------------------------------------------------------


class TestNtripStringRepresentations:
    """Tests for __str__ and __repr__."""

    def test_str_when_disconnected(self, dest_v1: NtripDestination) -> None:
        s = str(dest_v1)
        assert "ntrip" in s
        assert "rtk2go" in s
        assert "disconnected" in s

    def test_repr(self, dest_v1: NtripDestination) -> None:
        r = repr(dest_v1)
        assert "NtripDestination" in r
        assert "rtk2go" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
