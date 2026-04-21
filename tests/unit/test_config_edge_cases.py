"""Additional edge case tests for config.py to improve coverage."""

import os
import tempfile
from typing import Any
from unittest.mock import patch
import pytest

from sp_rtk_base_relay.config import (
    InputConfig,
    ConfigManager,
    Config,
)
from sp_rtk_base_relay.exceptions import ConfigurationError


def _v2_surepath_dest(
    host: str = "example.com",
    port: int = 50010,
    username: str = "user",
    password: str = "pass",
    **overrides: Any,
) -> dict[str, Any]:
    """Helper to create a v2 surepath destination dict."""
    dest: dict[str, Any] = {
        "name": "surepath",
        "type": "surepath",
        "enabled": True,
        "filter": {"mode": "pass_all"},
        "config": {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        },
    }
    dest["config"].update(overrides)
    return dest


def _v2_config_data(
    destinations: list[dict[str, Any]] | None = None,
    input_data: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Helper to build a complete v2 config dict."""
    data: dict[str, Any] = {
        "input": input_data or {
            "source": "tcp",
            "config": {"host": "127.0.0.1", "port": 5015},
        },
        "destinations": destinations or [_v2_surepath_dest()],
    }
    data.update(extra)
    return data


class TestInputConfigEdgeCases:
    """Edge case tests for InputConfig validation."""

    def test_tcp_config_with_generic_exception(self) -> None:
        """Test TCP config validation with non-ConfigurationError exception."""
        with patch("sp_rtk_base_relay.config.TCPInputConfig") as mock_tcp:
            mock_tcp.side_effect = ValueError("Some unexpected error")

            with pytest.raises(
                ConfigurationError, match="Invalid TCP input configuration"
            ):
                InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 5015})

    def test_serial_config_with_generic_exception(self) -> None:
        """Test serial config validation with non-ConfigurationError exception."""
        with patch("sp_rtk_base_relay.config.SerialInputConfig") as mock_serial:
            mock_serial.side_effect = TypeError("Some unexpected error")

            with pytest.raises(
                ConfigurationError, match="Invalid serial input configuration"
            ):
                InputConfig(
                    source="serial", config={"port": "/dev/ttyUSB0", "baudrate": 115200}
                )

    def test_usb_serial_config_with_generic_exception(self) -> None:
        """Test USB serial config validation with non-ConfigurationError exception."""
        with patch("sp_rtk_base_relay.config.SerialInputConfig") as mock_serial:
            mock_serial.side_effect = RuntimeError("Some unexpected error")

            with pytest.raises(
                ConfigurationError, match="Invalid serial input configuration"
            ):
                InputConfig(
                    source="usb_serial",
                    config={"port": "/dev/ttyUSB0", "baudrate": 115200},
                )


class TestConfigManagerEdgeCases:
    """Edge case tests for ConfigManager."""

    def test_load_config_no_path_no_env_no_defaults(self) -> None:
        """Test load_config when no config file is found anywhere."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(
                    ConfigurationError, match="No configuration file found"
                ):
                    ConfigManager.load_config()

    def test_load_config_with_env_config_path(self) -> None:
        """Test load_config with SP_BASE_RELAY_CONFIG environment variable (v2 format)."""
        import yaml

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_v2_config_data(
                destinations=[_v2_surepath_dest(host="env-test.example.com")]
            ), f)
            config_path = f.name

        try:
            with patch.dict(os.environ, {"SP_BASE_RELAY_CONFIG": config_path}):
                config = ConfigManager.load_config()
                from sp_rtk_base_relay.config import SurePathDestinationConfig
                assert isinstance(config.destinations[0].config, SurePathDestinationConfig)
                assert config.destinations[0].config.host == "env-test.example.com"
        finally:
            os.unlink(config_path)

    def test_load_config_generic_read_exception(self) -> None:
        """Test load_config with generic exception during file read."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with patch("pathlib.Path.exists", return_value=True):
                with pytest.raises(
                    ConfigurationError, match="Error reading configuration file"
                ):
                    ConfigManager.load_config("/test/config.yaml")

    def test_load_config_without_env_overrides(self) -> None:
        """Test load_config with env overrides disabled (v2 format)."""
        import yaml

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_v2_config_data(
                destinations=[_v2_surepath_dest(host="test.example.com")]
            ), f)
            config_path = f.name

        try:
            with patch.dict(
                os.environ, {"SP_DEST_SUREPATH_HOST": "ignored.example.com"}
            ):
                config = ConfigManager.load_config(
                    config_path, apply_env_overrides=False
                )
                from sp_rtk_base_relay.config import SurePathDestinationConfig
                assert isinstance(config.destinations[0].config, SurePathDestinationConfig)
                assert config.destinations[0].config.host == "test.example.com"
        finally:
            os.unlink(config_path)

    def test_apply_env_overrides_boolean_conversions(self) -> None:
        """Test environment variable boolean type conversions."""
        data = _v2_config_data(metrics={"enabled": False})

        test_cases = [
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("TRUE", True),
            ("FALSE", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(os.environ, {"SP_METRICS_ENABLED": env_value}):
                result = ConfigManager._apply_env_overrides(data.copy())  # type: ignore[attr-defined]
                assert result["metrics"]["enabled"] is expected

    def test_apply_env_overrides_float_conversion(self) -> None:
        """Test environment variable float type conversions."""
        data = _v2_config_data()

        with patch.dict(
            os.environ,
            {"SP_INPUT_TCP_TIMEOUT": "10.5"},
        ):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["input"]["config"]["timeout"] == 10.5

    def test_apply_env_overrides_invalid_int_conversion(self) -> None:
        """Test environment variable with invalid integer value."""
        data = _v2_config_data(metrics={"port": 8080})

        with patch.dict(os.environ, {"SP_METRICS_PORT": "not_a_number"}):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            # Invalid int: _convert_env_value returns original string
            assert result["metrics"]["port"] == "not_a_number"

    def test_apply_env_overrides_invalid_float_conversion(self) -> None:
        """Test environment variable with invalid float value."""
        data = _v2_config_data()

        with patch.dict(os.environ, {"SP_INPUT_TCP_TIMEOUT": "invalid"}):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["input"]["config"]["timeout"] == "invalid"

    def test_apply_env_overrides_creates_nested_structure(self) -> None:
        """Test that env overrides create nested structure if not exists."""
        data: dict[str, Any] = {
            "destinations": [_v2_surepath_dest()],
        }

        with patch.dict(
            os.environ,
            {
                "SP_INPUT_SOURCE": "tcp",
                "SP_INPUT_TCP_HOST": "192.168.1.1",
                "SP_INPUT_TCP_PORT": "9090",
            },
        ):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert "input" in result
            assert result["input"]["source"] == "tcp"
            assert result["input"]["config"]["host"] == "192.168.1.1"
            assert result["input"]["config"]["port"] == 9090

    def test_validate_config_file_with_unexpected_error(self) -> None:
        """Test validate_config_file with unexpected error."""
        with patch.object(
            ConfigManager, "load_config", side_effect=RuntimeError("Unexpected error")
        ):
            with pytest.raises(
                ConfigurationError, match="Unexpected error validating configuration"
            ):
                ConfigManager.validate_config_file("/test/config.yaml")

    def test_config_from_dict_with_invalid_input_type(self) -> None:
        """Test Config.from_dict with non-dict input."""
        with pytest.raises(
            ConfigurationError,
            match="Invalid configuration format: expected dictionary",
        ):
            Config.from_dict([])  # type: ignore

    def test_config_from_dict_with_string_input(self) -> None:
        """Test Config.from_dict with string input."""
        with pytest.raises(
            ConfigurationError,
            match="Invalid configuration format: expected dictionary",
        ):
            Config.from_dict("not a dict")  # type: ignore

    def test_config_from_dict_reraises_configuration_error(self) -> None:
        """Test that Config.from_dict re-raises ConfigurationError (v2)."""
        data = _v2_config_data(
            destinations=[_v2_surepath_dest(host="")]  # Will cause ConfigurationError
        )

        with pytest.raises(
            ConfigurationError, match="config.host cannot be empty"
        ):
            Config.from_dict(data)

    def test_dest_env_override_dynamic(self) -> None:
        """Test dynamic SP_DEST_<NAME>_<FIELD> env overrides."""
        data = _v2_config_data(
            destinations=[
                {
                    "name": "rtk2go",
                    "type": "ntrip",
                    "enabled": True,
                    "filter": {"mode": "pass_all"},
                    "config": {
                        "caster": "rtk2go.com",
                        "port": 2101,
                        "mountpoint": "MOUNT1",
                        "password": "orig_pass",
                    },
                }
            ]
        )

        with patch.dict(os.environ, {
            "SP_DEST_RTK2GO_PASSWORD": "new_pass",
            "SP_DEST_RTK2GO_PORT": "2102",
        }):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["destinations"][0]["config"]["password"] == "new_pass"
            assert result["destinations"][0]["config"]["port"] == 2102


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
