"""Additional edge case tests for config.py to improve coverage."""

import os
import tempfile
from unittest.mock import patch
import pytest

from sp_base_relay.config import (
    InputConfig,
    ConfigManager,
    Config,
)
from sp_base_relay.exceptions import ConfigurationError


class TestInputConfigEdgeCases:
    """Edge case tests for InputConfig validation."""

    def test_tcp_config_with_generic_exception(self):
        """Test TCP config validation with non-ConfigurationError exception."""
        # Mock TCPInputConfig to raise a generic exception
        with patch("sp_base_relay.config.TCPInputConfig") as mock_tcp:
            mock_tcp.side_effect = ValueError("Some unexpected error")

            with pytest.raises(
                ConfigurationError, match="Invalid TCP input configuration"
            ):
                InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 5015})

    def test_serial_config_with_generic_exception(self):
        """Test serial config validation with non-ConfigurationError exception."""
        # Mock SerialInputConfig to raise a generic exception
        with patch("sp_base_relay.config.SerialInputConfig") as mock_serial:
            mock_serial.side_effect = TypeError("Some unexpected error")

            with pytest.raises(
                ConfigurationError, match="Invalid serial input configuration"
            ):
                InputConfig(
                    source="serial", config={"port": "/dev/ttyUSB0", "baudrate": 115200}
                )

    def test_usb_serial_config_with_generic_exception(self):
        """Test USB serial config validation with non-ConfigurationError exception."""
        # Mock SerialInputConfig to raise a generic exception for usb_serial
        with patch("sp_base_relay.config.SerialInputConfig") as mock_serial:
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

    def test_load_config_no_path_no_env_no_defaults(self):
        """Test load_config when no config file is found anywhere."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(
                    ConfigurationError, match="No configuration file found"
                ):
                    ConfigManager.load_config()

    def test_load_config_with_env_config_path(self):
        """Test load_config with SP_BASE_RELAY_CONFIG environment variable."""
        test_config = """
server:
  host: "env-test.example.com"
  port: 8080
  username: "envuser"
  password: "envpass"
input:
  source: "tcp"
  config:
    host: "127.0.0.1"
    port: 5015
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            config_path = f.name

        try:
            with patch.dict(os.environ, {"SP_BASE_RELAY_CONFIG": config_path}):
                config = ConfigManager.load_config()
                assert config.server.host == "env-test.example.com"
        finally:
            os.unlink(config_path)

    def test_load_config_generic_read_exception(self):
        """Test load_config with generic exception during file read."""
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with patch("pathlib.Path.exists", return_value=True):
                with pytest.raises(
                    ConfigurationError, match="Error reading configuration file"
                ):
                    ConfigManager.load_config("/test/config.yaml")

    def test_load_config_without_env_overrides(self):
        """Test load_config with env overrides disabled."""
        test_config = """
server:
  host: "test.example.com"
  port: 8080
  username: "user"
  password: "pass"
input:
  source: "tcp"
  config:
    host: "127.0.0.1"
    port: 5015
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            config_path = f.name

        try:
            # Set env var that should be ignored
            with patch.dict(os.environ, {"SP_RTCM_HOST": "ignored.example.com"}):
                config = ConfigManager.load_config(
                    config_path, apply_env_overrides=False
                )
                # Should use config file value, not env override
                assert config.server.host == "test.example.com"
        finally:
            os.unlink(config_path)

    def test_apply_env_overrides_boolean_conversions(self):
        """Test environment variable boolean type conversions."""
        data = {
            "server": {
                "host": "test",
                "port": 8080,
                "username": "user",
                "password": "pass",
            },
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}},
            "metrics": {"enabled": False},
        }

        # Test various boolean representations
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

    def test_apply_env_overrides_float_conversion(self):
        """Test environment variable float type conversions."""
        data = {
            "server": {
                "host": "test",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "retry_multiplier": 2.0,
            },
            "input": {
                "source": "tcp",
                "config": {"host": "127.0.0.1", "port": 5015, "timeout": 5.0},
            },
        }

        with patch.dict(
            os.environ,
            {"SP_RTCM_RETRY_MULTIPLIER": "3.5", "SP_INPUT_TCP_TIMEOUT": "10.5"},
        ):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["server"]["retry_multiplier"] == 3.5
            assert result["input"]["config"]["timeout"] == 10.5

    def test_apply_env_overrides_invalid_int_conversion(self):
        """Test environment variable with invalid integer value."""
        data = {
            "server": {
                "host": "test",
                "port": 8080,
                "username": "user",
                "password": "pass",
            },
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}},
            "metrics": {"port": 8080},
        }

        # Invalid int should be ignored, original value kept
        with patch.dict(os.environ, {"SP_METRICS_PORT": "not_a_number"}):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["metrics"]["port"] == 8080  # Original value kept

    def test_apply_env_overrides_invalid_float_conversion(self):
        """Test environment variable with invalid float value."""
        data = {
            "server": {
                "host": "test",
                "port": 8080,
                "username": "user",
                "password": "pass",
                "retry_multiplier": 2.0,
            },
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}},
        }

        # Invalid float should be ignored, original value kept
        with patch.dict(os.environ, {"SP_RTCM_RETRY_MULTIPLIER": "invalid"}):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["server"]["retry_multiplier"] == 2.0  # Original value kept

    def test_apply_env_overrides_creates_nested_structure(self):
        """Test that env overrides create nested structure if not exists."""
        data = {
            "server": {
                "host": "test",
                "port": 8080,
                "username": "user",
                "password": "pass",
            }
        }

        # Apply env var for input config that doesn't exist in data
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

    def test_validate_config_file_with_unexpected_error(self):
        """Test validate_config_file with unexpected error."""
        with patch.object(
            ConfigManager, "load_config", side_effect=RuntimeError("Unexpected error")
        ):
            with pytest.raises(
                ConfigurationError, match="Unexpected error validating configuration"
            ):
                ConfigManager.validate_config_file("/test/config.yaml")

    def test_config_from_dict_with_invalid_input_type(self):
        """Test Config.from_dict with non-dict input."""
        with pytest.raises(
            ConfigurationError,
            match="Invalid configuration format: expected dictionary",
        ):
            Config.from_dict([])  # type: ignore

    def test_config_from_dict_with_string_input(self):
        """Test Config.from_dict with string input."""
        with pytest.raises(
            ConfigurationError,
            match="Invalid configuration format: expected dictionary",
        ):
            Config.from_dict("not a dict")  # type: ignore

    def test_config_from_dict_reraises_configuration_error(self):
        """Test that Config.from_dict re-raises ConfigurationError."""
        data = {
            "server": {
                "host": "",  # Will cause ConfigurationError
                "port": 8080,
                "username": "user",
                "password": "pass",
            },
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}},
        }

        with pytest.raises(ConfigurationError, match="server.host cannot be empty"):
            Config.from_dict(data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
