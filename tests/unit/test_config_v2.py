"""Tests for v2.0 destination configuration dataclasses.

Tests DestinationFilterConfig, SurePathDestinationConfig, NtripDestinationConfig,
TcpServerDestinationConfig, DestinationConfig, and Config v2 parsing.
"""

from typing import Any

import pytest

from sp_base_relay.config import (
    Config,
    DestinationConfig,
    DestinationFilterConfig,
    NtripDestinationConfig,
    SurePathDestinationConfig,
    TcpServerDestinationConfig,
)
from sp_base_relay.exceptions import ConfigurationError


# ============================================================================
# Helpers
# ============================================================================

def _surepath_dest(
    name: str = "surepath",
    enabled: bool = True,
    host: str = "example.com",
    port: int = 50010,
    username: str = "user",
    password: str = "pass",
    filter_mode: str = "pass_all",
    filter_ids: list[int] | None = None,
    **config_overrides: Any,
) -> dict[str, Any]:
    """Build a surepath destination dict."""
    dest: dict[str, Any] = {
        "name": name,
        "type": "surepath",
        "enabled": enabled,
        "filter": {"mode": filter_mode},
        "config": {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        },
    }
    if filter_ids is not None:
        dest["filter"]["message_ids"] = filter_ids
    dest["config"].update(config_overrides)
    return dest


def _ntrip_dest(
    name: str = "rtk2go",
    enabled: bool = True,
    caster: str = "rtk2go.com",
    port: int = 2101,
    mountpoint: str = "MOUNT1",
    password: str = "pass",
    version: str = "2.0",
    filter_mode: str = "pass_all",
    filter_ids: list[int] | None = None,
    **config_overrides: Any,
) -> dict[str, Any]:
    """Build an NTRIP destination dict."""
    dest: dict[str, Any] = {
        "name": name,
        "type": "ntrip",
        "enabled": enabled,
        "filter": {"mode": filter_mode},
        "config": {
            "caster": caster,
            "port": port,
            "mountpoint": mountpoint,
            "password": password,
            "version": version,
        },
    }
    if filter_ids is not None:
        dest["filter"]["message_ids"] = filter_ids
    dest["config"].update(config_overrides)
    return dest


def _tcp_server_dest(
    name: str = "local_tcp",
    enabled: bool = True,
    host: str = "0.0.0.0",
    port: int = 5016,
    max_clients: int = 10,
    **config_overrides: Any,
) -> dict[str, Any]:
    """Build a TCP server destination dict."""
    dest: dict[str, Any] = {
        "name": name,
        "type": "tcp_server",
        "enabled": enabled,
        "filter": {"mode": "pass_all"},
        "config": {
            "host": host,
            "port": port,
            "max_clients": max_clients,
        },
    }
    dest["config"].update(config_overrides)
    return dest


def _v2_data(
    destinations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build minimal v2 config data."""
    return {
        "input": {
            "source": "tcp",
            "config": {"host": "127.0.0.1", "port": 5015},
        },
        "destinations": destinations if destinations is not None else [_surepath_dest()],
    }


# ============================================================================
# DestinationFilterConfig
# ============================================================================

class TestDestinationFilterConfig:
    """Tests for DestinationFilterConfig dataclass."""

    def test_pass_all_default(self) -> None:
        f = DestinationFilterConfig()
        assert f.mode == "pass_all"
        assert f.message_ids == []

    def test_pass_all_explicit(self) -> None:
        f = DestinationFilterConfig(mode="pass_all", message_ids=[])
        assert f.mode == "pass_all"

    def test_allowlist(self) -> None:
        f = DestinationFilterConfig(mode="allowlist", message_ids=[1005, 1077])
        assert f.mode == "allowlist"
        assert f.message_ids == [1005, 1077]

    def test_blocklist(self) -> None:
        f = DestinationFilterConfig(mode="blocklist", message_ids=[4072])
        assert f.mode == "blocklist"

    def test_invalid_mode(self) -> None:
        with pytest.raises(ConfigurationError, match="filter.mode must be one of"):
            DestinationFilterConfig(mode="invalid")

    def test_pass_all_with_ids_rejects(self) -> None:
        with pytest.raises(ConfigurationError, match="must be empty when mode is"):
            DestinationFilterConfig(mode="pass_all", message_ids=[1005])

    def test_allowlist_without_ids_rejects(self) -> None:
        with pytest.raises(ConfigurationError, match="message_ids is required"):
            DestinationFilterConfig(mode="allowlist", message_ids=[])

    def test_blocklist_without_ids_rejects(self) -> None:
        with pytest.raises(ConfigurationError, match="message_ids is required"):
            DestinationFilterConfig(mode="blocklist", message_ids=[])

    def test_to_filter_config_pass_all(self) -> None:
        f = DestinationFilterConfig(mode="pass_all")
        fc = f.to_filter_config()
        assert fc.mode.value == "pass_all"
        assert fc.message_ids == frozenset()

    def test_to_filter_config_allowlist(self) -> None:
        f = DestinationFilterConfig(mode="allowlist", message_ids=[1005, 1077])
        fc = f.to_filter_config()
        assert fc.mode.value == "allowlist"
        assert fc.message_ids == frozenset({1005, 1077})

    def test_to_filter_config_blocklist(self) -> None:
        f = DestinationFilterConfig(mode="blocklist", message_ids=[4072])
        fc = f.to_filter_config()
        assert fc.mode.value == "blocklist"
        assert fc.message_ids == frozenset({4072})


# ============================================================================
# SurePathDestinationConfig
# ============================================================================

class TestSurePathDestinationConfig:
    """Tests for SurePathDestinationConfig dataclass."""

    def test_valid_config(self) -> None:
        c = SurePathDestinationConfig(
            host="example.com", port=50010, username="user", password="pass"
        )
        assert c.host == "example.com"
        assert c.port == 50010
        assert c.connection_timeout == 10
        assert c.retry_multiplier == 2.0

    def test_empty_host(self) -> None:
        with pytest.raises(ConfigurationError, match="host cannot be empty"):
            SurePathDestinationConfig(host="", port=50010, username="u", password="p")

    def test_invalid_port(self) -> None:
        with pytest.raises(ConfigurationError, match="port must be 1-65535"):
            SurePathDestinationConfig(host="h", port=0, username="u", password="p")

    def test_empty_username(self) -> None:
        with pytest.raises(ConfigurationError, match="username cannot be empty"):
            SurePathDestinationConfig(host="h", port=50010, username="", password="p")

    def test_empty_password(self) -> None:
        with pytest.raises(ConfigurationError, match="password cannot be empty"):
            SurePathDestinationConfig(host="h", port=50010, username="u", password="")

    def test_invalid_connection_timeout(self) -> None:
        with pytest.raises(ConfigurationError, match="connection_timeout must be positive"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p", connection_timeout=0
            )

    def test_invalid_read_timeout(self) -> None:
        with pytest.raises(ConfigurationError, match="read_timeout must be positive"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p", read_timeout=-1
            )

    def test_invalid_heartbeat_timeout(self) -> None:
        with pytest.raises(ConfigurationError, match="heartbeat_timeout must be positive"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p", heartbeat_timeout=0
            )

    def test_invalid_retry_initial_delay(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_initial_delay must be positive"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p", retry_initial_delay=-1
            )

    def test_invalid_retry_max_delay(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_max_delay.*must be >= retry_initial_delay"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p",
                retry_initial_delay=20, retry_max_delay=10,
            )

    def test_invalid_retry_multiplier(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_multiplier must be > 1.0"):
            SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p", retry_multiplier=0.5
            )

    def test_to_rtcm_server_config(self) -> None:
        c = SurePathDestinationConfig(
            host="test.com", port=50010, username="u", password="p",
            connection_timeout=15, retry_multiplier=3.0,
        )
        rtcm = c.to_rtcm_server_config()
        assert rtcm.host == "test.com"
        assert rtcm.port == 50010
        assert rtcm.username == "u"
        assert rtcm.connection_timeout == 15
        assert rtcm.retry_multiplier == 3.0


# ============================================================================
# NtripDestinationConfig
# ============================================================================

class TestNtripDestinationConfig:
    """Tests for NtripDestinationConfig dataclass."""

    def test_valid_v2_config(self) -> None:
        c = NtripDestinationConfig(
            caster="rtk2go.com", mountpoint="MOUNT1", password="pass"
        )
        assert c.caster == "rtk2go.com"
        assert c.port == 2101
        assert c.version == "2.0"
        assert c.retry_initial_delay == 10

    def test_valid_v1_config(self) -> None:
        c = NtripDestinationConfig(
            caster="rtk2go.com", mountpoint="MOUNT1", password="pass", version="1.0"
        )
        assert c.version == "1.0"

    def test_empty_caster(self) -> None:
        with pytest.raises(ConfigurationError, match="caster cannot be empty"):
            NtripDestinationConfig(caster="", mountpoint="M", password="p")

    def test_invalid_port(self) -> None:
        with pytest.raises(ConfigurationError, match="port must be 1-65535"):
            NtripDestinationConfig(caster="c", port=0, mountpoint="M", password="p")

    def test_empty_mountpoint(self) -> None:
        with pytest.raises(ConfigurationError, match="mountpoint cannot be empty"):
            NtripDestinationConfig(caster="c", mountpoint="", password="p")

    def test_empty_password(self) -> None:
        with pytest.raises(ConfigurationError, match="password cannot be empty"):
            NtripDestinationConfig(caster="c", mountpoint="M", password="")

    def test_invalid_version(self) -> None:
        with pytest.raises(ConfigurationError, match="version must be one of"):
            NtripDestinationConfig(
                caster="c", mountpoint="M", password="p", version="3.0"
            )

    def test_invalid_connection_timeout(self) -> None:
        with pytest.raises(ConfigurationError, match="connection_timeout must be positive"):
            NtripDestinationConfig(
                caster="c", mountpoint="M", password="p", connection_timeout=0
            )

    def test_invalid_retry_initial_delay(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_initial_delay must be positive"):
            NtripDestinationConfig(
                caster="c", mountpoint="M", password="p", retry_initial_delay=-1
            )

    def test_invalid_retry_max_delay(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_max_delay.*must be >= retry_initial_delay"):
            NtripDestinationConfig(
                caster="c", mountpoint="M", password="p",
                retry_initial_delay=20, retry_max_delay=10,
            )

    def test_invalid_retry_multiplier(self) -> None:
        with pytest.raises(ConfigurationError, match="retry_multiplier must be > 1.0"):
            NtripDestinationConfig(
                caster="c", mountpoint="M", password="p", retry_multiplier=1.0
            )


# ============================================================================
# TcpServerDestinationConfig
# ============================================================================

class TestTcpServerDestinationConfig:
    """Tests for TcpServerDestinationConfig dataclass."""

    def test_valid_defaults(self) -> None:
        c = TcpServerDestinationConfig()
        assert c.host == "0.0.0.0"
        assert c.port == 5016
        assert c.max_clients == 10

    def test_custom_config(self) -> None:
        c = TcpServerDestinationConfig(host="127.0.0.1", port=9000, max_clients=5)
        assert c.host == "127.0.0.1"
        assert c.port == 9000
        assert c.max_clients == 5

    def test_invalid_port(self) -> None:
        with pytest.raises(ConfigurationError, match="port must be 1-65535"):
            TcpServerDestinationConfig(port=0)

    def test_invalid_max_clients(self) -> None:
        with pytest.raises(ConfigurationError, match="max_clients must be >= 1"):
            TcpServerDestinationConfig(max_clients=0)


# ============================================================================
# DestinationConfig
# ============================================================================

class TestDestinationConfig:
    """Tests for DestinationConfig wrapper."""

    def test_valid_surepath(self) -> None:
        c = DestinationConfig(
            name="surepath",
            type="surepath",
            enabled=True,
            filter=DestinationFilterConfig(),
            config=SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p"
            ),
        )
        assert c.name == "surepath"
        assert c.type == "surepath"
        assert c.enabled is True

    def test_empty_name(self) -> None:
        with pytest.raises(ConfigurationError, match="name cannot be empty"):
            DestinationConfig(
                name="",
                type="surepath",
                enabled=True,
                filter=DestinationFilterConfig(),
                config=SurePathDestinationConfig(
                    host="h", port=50010, username="u", password="p"
                ),
            )

    def test_invalid_name_chars(self) -> None:
        with pytest.raises(ConfigurationError, match="must be alphanumeric"):
            DestinationConfig(
                name="bad name!",
                type="surepath",
                enabled=True,
                filter=DestinationFilterConfig(),
                config=SurePathDestinationConfig(
                    host="h", port=50010, username="u", password="p"
                ),
            )

    def test_name_with_underscores_hyphens(self) -> None:
        c = DestinationConfig(
            name="my-dest_01",
            type="surepath",
            enabled=True,
            filter=DestinationFilterConfig(),
            config=SurePathDestinationConfig(
                host="h", port=50010, username="u", password="p"
            ),
        )
        assert c.name == "my-dest_01"

    def test_invalid_type(self) -> None:
        with pytest.raises(ConfigurationError, match="must be one of"):
            DestinationConfig(
                name="test",
                type="invalid",
                enabled=True,
                filter=DestinationFilterConfig(),
                config=SurePathDestinationConfig(
                    host="h", port=50010, username="u", password="p"
                ),
            )


# ============================================================================
# Config.from_dict v2 — Destination Parsing
# ============================================================================

class TestConfigV2Destinations:
    """Tests for Config.from_dict v2 destination parsing."""

    def test_single_surepath(self) -> None:
        config = Config.from_dict(_v2_data([_surepath_dest()]))
        assert len(config.destinations) == 1
        assert config.destinations[0].type == "surepath"
        assert isinstance(config.destinations[0].config, SurePathDestinationConfig)

    def test_single_ntrip(self) -> None:
        config = Config.from_dict(_v2_data([_ntrip_dest()]))
        assert len(config.destinations) == 1
        assert isinstance(config.destinations[0].config, NtripDestinationConfig)
        assert config.destinations[0].config.version == "2.0"

    def test_single_tcp_server(self) -> None:
        config = Config.from_dict(_v2_data([_tcp_server_dest()]))
        assert len(config.destinations) == 1
        assert isinstance(config.destinations[0].config, TcpServerDestinationConfig)

    def test_multiple_destinations(self) -> None:
        config = Config.from_dict(_v2_data([
            _surepath_dest(),
            _ntrip_dest(name="rtk2go"),
            _ntrip_dest(name="onocoy", caster="onocoy.com"),
            _tcp_server_dest(name="local_tcp", enabled=False),
        ]))
        assert len(config.destinations) == 4
        assert config.destinations[0].type == "surepath"
        assert config.destinations[1].type == "ntrip"
        assert config.destinations[3].enabled is False

    def test_get_enabled_destinations(self) -> None:
        config = Config.from_dict(_v2_data([
            _surepath_dest(),
            _tcp_server_dest(name="local_tcp", enabled=False),
        ]))
        enabled = config.get_enabled_destinations()
        assert len(enabled) == 1
        assert enabled[0].name == "surepath"

    def test_get_destination_by_name(self) -> None:
        config = Config.from_dict(_v2_data([
            _surepath_dest(),
            _ntrip_dest(name="rtk2go"),
        ]))
        dest = config.get_destination_by_name("rtk2go")
        assert dest is not None
        assert dest.type == "ntrip"

    def test_get_destination_by_name_not_found(self) -> None:
        config = Config.from_dict(_v2_data())
        assert config.get_destination_by_name("nonexistent") is None

    def test_filter_parsing_blocklist(self) -> None:
        config = Config.from_dict(_v2_data([
            _ntrip_dest(filter_mode="blocklist", filter_ids=[4072]),
        ]))
        assert config.destinations[0].filter.mode == "blocklist"
        assert config.destinations[0].filter.message_ids == [4072]

    def test_filter_parsing_allowlist(self) -> None:
        config = Config.from_dict(_v2_data([
            _ntrip_dest(
                name="rtkdirect",
                filter_mode="allowlist",
                filter_ids=[1005, 1077, 1087],
            ),
        ]))
        assert config.destinations[0].filter.mode == "allowlist"
        assert config.destinations[0].filter.message_ids == [1005, 1077, 1087]

    def test_duplicate_names_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="Duplicate destination name"):
            Config.from_dict(_v2_data([
                _surepath_dest(name="dup"),
                _ntrip_dest(name="dup"),
            ]))

    def test_no_enabled_destinations_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="At least one destination must be enabled"):
            Config.from_dict(_v2_data([
                _surepath_dest(enabled=False),
            ]))

    def test_empty_destinations_list_rejected(self) -> None:
        with pytest.raises(ConfigurationError, match="destinations must be a non-empty list"):
            Config.from_dict(_v2_data(destinations=[]))

    def test_destinations_not_list_rejected(self) -> None:
        data = _v2_data()
        data["destinations"] = "not_a_list"
        with pytest.raises(ConfigurationError, match="destinations must be a non-empty list"):
            Config.from_dict(data)

    def test_destination_not_dict_rejected(self) -> None:
        data = _v2_data()
        data["destinations"] = ["not_a_dict"]
        with pytest.raises(ConfigurationError, match="must be a dictionary"):
            Config.from_dict(data)

    def test_missing_destination_name(self) -> None:
        dest = _surepath_dest()
        del dest["name"]
        with pytest.raises(ConfigurationError, match="name is required"):
            Config.from_dict(_v2_data([dest]))

    def test_missing_destination_type(self) -> None:
        dest = _surepath_dest()
        del dest["type"]
        with pytest.raises(ConfigurationError, match="type is required"):
            Config.from_dict(_v2_data([dest]))

    def test_invalid_destination_type(self) -> None:
        dest = _surepath_dest()
        dest["type"] = "invalid"
        with pytest.raises(ConfigurationError, match="must be one of"):
            Config.from_dict(_v2_data([dest]))

    def test_enabled_not_bool_rejected(self) -> None:
        dest = _surepath_dest()
        dest["enabled"] = "yes"
        with pytest.raises(ConfigurationError, match="enabled must be a boolean"):
            Config.from_dict(_v2_data([dest]))

    def test_filter_not_dict_rejected(self) -> None:
        dest = _surepath_dest()
        dest["filter"] = "pass_all"
        with pytest.raises(ConfigurationError, match="filter must be a dictionary"):
            Config.from_dict(_v2_data([dest]))

    def test_config_not_dict_rejected(self) -> None:
        dest = _surepath_dest()
        dest["config"] = "not_dict"
        with pytest.raises(ConfigurationError, match="config must be a dictionary"):
            Config.from_dict(_v2_data([dest]))

    def test_config_invalid_fields_rejected(self) -> None:
        dest = _surepath_dest()
        dest["config"]["unknown_field"] = "value"
        with pytest.raises(ConfigurationError, match="invalid fields"):
            Config.from_dict(_v2_data([dest]))

    def test_default_filter_is_pass_all(self) -> None:
        """If filter block is omitted, default to pass_all."""
        dest = _surepath_dest()
        del dest["filter"]
        config = Config.from_dict(_v2_data([dest]))
        assert config.destinations[0].filter.mode == "pass_all"

    def test_default_config_is_empty_dict(self) -> None:
        """If config block is omitted, empty dict passed to dataclass."""
        dest = _ntrip_dest()
        del dest["config"]
        # NTRIP requires caster, so this should fail validation
        with pytest.raises(ConfigurationError, match="caster cannot be empty"):
            Config.from_dict(_v2_data([dest]))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
