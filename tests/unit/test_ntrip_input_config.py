"""Tests for validating an `ntrip` input's configuration.

Seam under test: InputConfig(source="ntrip", config={...}), as the service's
config file and RelayEngine supply it.
"""

from pathlib import Path
from typing import Any

import pytest

from sp_rtk_base_relay.config import ConfigManager, InputConfig
from sp_rtk_base_relay.exceptions import ConfigurationError


def _ntrip(**overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"caster": "caster.example", "mountpoint": "MP1"}
    config.update(overrides)
    return config


def test_a_minimal_config_gets_the_destination_defaults() -> None:
    config = InputConfig(source="ntrip", config=_ntrip()).get_ntrip_config()

    assert (config.caster, config.port, config.mountpoint) == (
        "caster.example",
        2101,
        "MP1",
    )
    assert (config.username, config.password) == ("", "")
    assert config.version == "2.0"
    assert config.tls is False
    assert config.data_timeout == 30.0
    assert (
        config.retry_initial_delay,
        config.retry_max_delay,
        config.retry_multiplier,
    ) == (
        10,
        120,
        2.0,
    )


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"mountpoint": "MP1"}, "caster"),
        (_ntrip(caster=""), "caster"),
        ({"caster": "caster.example"}, "mountpoint"),
        (_ntrip(mountpoint=""), "mountpoint"),
        (_ntrip(version="1.0", tls=True), "tls"),
        (_ntrip(version="3.0"), "version"),
        (_ntrip(port=0), "port"),
        (_ntrip(connection_timeout=0), "connection_timeout"),
        (_ntrip(data_timeout=0), "data_timeout"),
        (_ntrip(retry_initial_delay=20, retry_max_delay=10), "retry_max_delay"),
        (_ntrip(retry_multiplier=1.0), "retry_multiplier"),
        (_ntrip(gga_interval=10), "gga_interval"),  # unknown field
    ],
)
def test_an_invalid_config_is_rejected_clearly(
    config: dict[str, Any], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        InputConfig(source="ntrip", config=config)


def test_tls_with_v2_is_accepted() -> None:
    config = InputConfig(source="ntrip", config=_ntrip(tls=True)).get_ntrip_config()

    assert config.tls is True


def test_an_ntrip_input_loads_from_the_service_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        """
input:
  source: ntrip
  config:
    caster: caster.example
    mountpoint: MP1
    username: rover
    password: roverpw
    version: "1.0"
destinations:
  - name: lan
    type: tcp_server
    config:
      port: 5016
"""
    )

    config = ConfigManager.load_config(str(path), apply_env_overrides=False)

    ntrip = config.input.get_ntrip_config()
    assert (ntrip.username, ntrip.version) == ("rover", "1.0")
