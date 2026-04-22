"""Tests for SurePathDestination — RTCMClient wrapped as BaseDestination.

Tests cover:
- Construction / initialisation
- _connect / _disconnect / _send_data / _is_connected delegation
- Backoff-aware _attempt_connect override
- get_connection_info
- Factory builder + auto-registration
- Edge cases (send failure, connection loss)
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from sp_rtk_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    NtripDestinationConfig,
    SurePathDestinationConfig,
)
from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
from sp_rtk_base_relay.core.destinations.surepath_destination import (
    SurePathDestination,
    build_surepath_destination,
)
from sp_rtk_base_relay.core.message_filter import FilterConfig, FilterMode
from sp_rtk_base_relay.core.rtcm_client import ConnectionStats, RTCMClient
from sp_rtk_base_relay.exceptions import ConfigurationError, DestinationError

# ============================================================================
# Helpers
# ============================================================================


def _default_filter() -> FilterConfig:
    return FilterConfig(mode=FilterMode.PASS_ALL, message_ids=frozenset())


def _default_surepath_config() -> SurePathDestinationConfig:
    return SurePathDestinationConfig(
        host="sp.example.com",
        port=50010,
        username="user1",
        password="pass1",
    )


def _make_dest(
    name: str = "sp1",
    filter_config: FilterConfig | None = None,
    surepath_config: SurePathDestinationConfig | None = None,
) -> SurePathDestination:
    """Create a SurePathDestination with mocked RTCMClient."""
    dest = SurePathDestination(
        name=name,
        filter_config=filter_config or _default_filter(),
        surepath_config=surepath_config or _default_surepath_config(),
    )
    # Replace the real RTCMClient with a mock
    dest._client = MagicMock(spec=RTCMClient)
    dest._client.is_connected = False
    dest._client.connection_state = MagicMock()
    dest._client.connection_state.value = "disconnected"
    dest._client.connection_statistics = ConnectionStats()
    dest._client.get_retry_delay.return_value = 5
    return dest


def _make_destination_config(
    name: str = "sp1",
    enabled: bool = True,
    filter_mode: str = "pass_all",
) -> DestinationConfig:
    return DestinationConfig(
        name=name,
        type="surepath",
        enabled=enabled,
        filter=DestinationFilterConfig(mode=filter_mode),
        config=SurePathDestinationConfig(
            host="sp.example.com",
            port=50010,
            username="user1",
            password="pass1",
        ),
    )


# ============================================================================
# Tests — Construction
# ============================================================================


class TestConstruction:
    """SurePathDestination initialisation."""

    def test_creates_with_correct_name(self) -> None:
        dest = _make_dest(name="my-surepath")
        assert dest.name == "my-surepath"

    def test_destination_type_is_surepath(self) -> None:
        dest = _make_dest()
        assert dest.destination_type == "surepath"

    def test_is_instance_of_base_destination(self) -> None:
        dest = _make_dest()
        assert isinstance(dest, BaseDestination)

    def test_default_queue_size(self) -> None:
        dest = _make_dest()
        assert dest._queue.maxsize == 100

    def test_custom_queue_size(self) -> None:
        dest = SurePathDestination(
            name="sp1",
            filter_config=_default_filter(),
            surepath_config=_default_surepath_config(),
            queue_size=50,
        )
        assert dest._queue.maxsize == 50

    def test_filter_config_applied(self) -> None:
        fc = FilterConfig(mode=FilterMode.ALLOWLIST, message_ids=frozenset({1005}))
        dest = _make_dest(filter_config=fc)
        assert dest.message_filter.mode == FilterMode.ALLOWLIST
        assert dest.message_filter.should_pass(1005) is True
        assert dest.message_filter.should_pass(9999) is False

    def test_next_connect_time_starts_at_zero(self) -> None:
        dest = _make_dest()
        assert dest._next_connect_time == 0.0

    @patch("sp_rtk_base_relay.core.destinations.surepath_destination.RTCMClient")
    def test_creates_rtcm_client_from_config(self, mock_cls: MagicMock) -> None:
        """Verify RTCMClient is constructed with converted config."""
        cfg = _default_surepath_config()
        SurePathDestination(
            name="sp1",
            filter_config=_default_filter(),
            surepath_config=cfg,
        )
        mock_cls.assert_called_once()
        # The argument should be an RTCMServerConfig
        call_args = mock_cls.call_args[0][0]
        assert call_args.host == "sp.example.com"
        assert call_args.port == 50010


# ============================================================================
# Tests — _connect / _disconnect
# ============================================================================


class TestConnectDisconnect:
    """Connection delegation to RTCMClient."""

    def test_connect_success(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = True
        # Should not raise
        dest._connect()
        dest._client.connect.assert_called_once()

    def test_connect_failure_raises_destination_error(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = False
        with pytest.raises(DestinationError, match="connect.*failed"):
            dest._connect()

    def test_disconnect_calls_client(self) -> None:
        dest = _make_dest()
        dest._disconnect()
        dest._client.disconnect.assert_called_once()

    def test_disconnect_resets_backoff_timer(self) -> None:
        dest = _make_dest()
        dest._next_connect_time = time.time() + 999
        dest._disconnect()
        assert dest._next_connect_time == 0.0


# ============================================================================
# Tests — _send_data
# ============================================================================


class TestSendData:
    """Data sending delegation."""

    def test_send_success(self) -> None:
        dest = _make_dest()
        dest._client.send_rtcm_data.return_value = True
        dest._send_data(b"\xd3\x00\x00")
        dest._client.send_rtcm_data.assert_called_once_with(b"\xd3\x00\x00")

    def test_send_failure_raises_os_error(self) -> None:
        dest = _make_dest()
        dest._client.send_rtcm_data.return_value = False
        with pytest.raises(OSError, match="send_rtcm_data returned False"):
            dest._send_data(b"\xd3\x00\x00")


# ============================================================================
# Tests — _is_connected
# ============================================================================


class TestIsConnected:
    """Connection state delegation."""

    def test_connected(self) -> None:
        dest = _make_dest()
        dest._client.is_connected = True
        assert dest._is_connected() is True

    def test_disconnected(self) -> None:
        dest = _make_dest()
        dest._client.is_connected = False
        assert dest._is_connected() is False


# ============================================================================
# Tests — get_connection_info
# ============================================================================


class TestConnectionInfo:
    """Connection info diagnostics."""

    def test_returns_expected_keys(self) -> None:
        dest = _make_dest()
        dest._client.is_connected = True
        dest._client.connection_state.value = "connected"
        info = dest.get_connection_info()
        assert info["name"] == "sp1"
        assert info["type"] == "surepath"
        assert info["host"] == "sp.example.com"
        assert info["port"] == 50010
        assert info["connected"] is True
        assert info["state"] == "connected"
        assert "bytes_sent" in info
        assert "heartbeat_timeouts" in info
        assert "auth_failures" in info


# ============================================================================
# Tests — Backoff-aware _attempt_connect
# ============================================================================


class TestBackoffConnect:
    """Override of _attempt_connect with exponential backoff."""

    def test_first_attempt_connects_immediately(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = True
        dest._client.is_connected = True
        dest._attempt_connect()
        dest._client.connect.assert_called_once()

    def test_failed_connect_sets_next_connect_time(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = False
        dest._client.is_connected = False
        dest._client.get_retry_delay.return_value = 10

        dest._attempt_connect()

        assert dest._next_connect_time > time.time()
        # Should be roughly now + 10s
        assert dest._next_connect_time <= time.time() + 11

    def test_skips_attempt_during_backoff(self) -> None:
        dest = _make_dest()
        dest._next_connect_time = time.time() + 999  # Far in the future
        dest._attempt_connect()
        dest._client.connect.assert_not_called()

    def test_attempts_after_backoff_expires(self) -> None:
        dest = _make_dest()
        dest._next_connect_time = time.time() - 1  # Already expired
        dest._client.connect.return_value = True
        dest._client.is_connected = True
        dest._attempt_connect()
        dest._client.connect.assert_called_once()

    def test_successful_connect_resets_next_connect_time(self) -> None:
        dest = _make_dest()
        dest._next_connect_time = time.time() + 999
        # Pretend backoff has expired so we actually attempt
        dest._next_connect_time = time.time() - 1
        dest._client.connect.return_value = True
        dest._client.is_connected = True
        dest._attempt_connect()
        assert dest._next_connect_time == 0.0

    def test_stats_updated_on_success(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = True
        dest._client.is_connected = True
        dest._attempt_connect()
        assert dest.stats.connection_attempts == 1
        assert dest.stats.successful_connections == 1

    def test_stats_updated_on_failure(self) -> None:
        dest = _make_dest()
        dest._client.connect.return_value = False
        dest._client.is_connected = False
        dest._attempt_connect()
        assert dest.stats.connection_attempts == 1
        assert dest.stats.connection_failures == 1


# ============================================================================
# Tests — client_stats property
# ============================================================================


class TestClientStats:
    """Exposure of underlying RTCMClient stats."""

    def test_client_stats_returns_rtcm_stats(self) -> None:
        dest = _make_dest()
        stats = ConnectionStats(bytes_sent=42, messages_sent=7)
        dest._client.connection_statistics = stats
        assert dest.client_stats.bytes_sent == 42
        assert dest.client_stats.messages_sent == 7


# ============================================================================
# Tests — Factory builder
# ============================================================================


class TestFactoryBuilder:
    """build_surepath_destination + auto-registration."""

    @patch("sp_rtk_base_relay.core.destinations.surepath_destination.RTCMClient")
    def test_build_creates_surepath_destination(self, mock_cls: MagicMock) -> None:
        cfg = _make_destination_config()
        dest = build_surepath_destination(cfg)
        assert isinstance(dest, SurePathDestination)
        assert dest.name == "sp1"

    @patch("sp_rtk_base_relay.core.destinations.surepath_destination.RTCMClient")
    def test_build_applies_filter(self, mock_cls: MagicMock) -> None:
        cfg = DestinationConfig(
            name="sp-filtered",
            type="surepath",
            enabled=True,
            filter=DestinationFilterConfig(
                mode="allowlist",
                message_ids=[1005, 1077],
            ),
            config=SurePathDestinationConfig(
                host="sp.example.com",
                port=50010,
                username="user1",
                password="pass1",
            ),
        )
        dest = build_surepath_destination(cfg)
        assert dest.message_filter.mode == FilterMode.ALLOWLIST

    def test_build_wrong_config_type_raises(self) -> None:
        cfg = DestinationConfig(
            name="bad",
            type="surepath",
            enabled=True,
            filter=DestinationFilterConfig(),
            config=NtripDestinationConfig(
                caster="rtk2go.com",
                port=2101,
                mountpoint="MOUNT",
                password="pass",
            ),
        )
        with pytest.raises(
            ConfigurationError, match="Expected SurePathDestinationConfig"
        ):
            build_surepath_destination(cfg)

    def test_surepath_auto_registered_in_factory(self) -> None:
        from sp_rtk_base_relay.core.destinations.destination_factory import (
            DestinationFactory,
        )

        assert DestinationFactory.is_registered("surepath")


# ============================================================================
# Tests — String representations
# ============================================================================


class TestStringRepresentations:
    """__str__ and __repr__ from BaseDestination."""

    def test_str_contains_name_and_type(self) -> None:
        dest = _make_dest()
        dest._client.is_connected = False
        s = str(dest)
        assert "surepath" in s
        assert "sp1" in s

    def test_repr_contains_class_name(self) -> None:
        dest = _make_dest()
        dest._client.is_connected = False
        r = repr(dest)
        assert "SurePathDestination" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
