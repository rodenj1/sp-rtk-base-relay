"""Unit tests for SP-Base-Relay configuration system."""

import os
import tempfile
import yaml
from unittest.mock import patch, mock_open
import pytest
from typing import Any

from sp_rtk_base_relay.config import (
    ServerConfig,
    TCPInputConfig,
    SerialInputConfig,
    InputConfig,
    MonitoringConfig,
    MetricsConfig,
    LoggingConfig,
    Config,
    ConfigManager,
)
from sp_rtk_base_relay.exceptions import ConfigurationError


class TestServerConfig:
    """Test server configuration."""

    def test_valid_server_config(self):
        """Test valid server configuration."""
        config = ServerConfig(
            host="example.com", port=8080, username="testuser", password="testpass"
        )
        assert config.host == "example.com"
        assert config.port == 8080
        assert config.username == "testuser"
        assert config.password == "testpass"
        # Test new RTCM parameters with defaults
        assert config.connection_timeout == 10
        assert config.read_timeout == 30
        assert config.heartbeat_timeout == 30
        assert config.retry_initial_delay == 15
        assert config.retry_max_delay == 60
        assert config.retry_multiplier == 2.0

    def test_valid_server_config_with_rtcm_params(self):
        """Test valid server configuration with custom RTCM parameters."""
        config = ServerConfig(
            host="example.com",
            port=8080,
            username="testuser",
            password="testpass",
            connection_timeout=15,
            read_timeout=45,
            heartbeat_timeout=60,
            retry_initial_delay=2,
            retry_max_delay=120,
            retry_multiplier=3.0,
        )
        assert config.connection_timeout == 15
        assert config.read_timeout == 45
        assert config.heartbeat_timeout == 60
        assert config.retry_initial_delay == 2
        assert config.retry_max_delay == 120
        assert config.retry_multiplier == 3.0

    def test_empty_host(self):
        """Test empty host validation."""
        with pytest.raises(ConfigurationError, match="server.host cannot be empty"):
            ServerConfig(host="", port=8080, username="user", password="pass")

    def test_invalid_port_low(self):
        """Test port too low."""
        with pytest.raises(
            ConfigurationError,
            match="server.port must be an integer between 1 and 65535",
        ):
            ServerConfig(host="example.com", port=0, username="user", password="pass")

    def test_invalid_port_high(self):
        """Test port too high."""
        with pytest.raises(
            ConfigurationError,
            match="server.port must be an integer between 1 and 65535",
        ):
            ServerConfig(
                host="example.com", port=65536, username="user", password="pass"
            )

    def test_invalid_port_type(self):
        """Test invalid port type."""
        with pytest.raises(
            ConfigurationError,
            match="server.port must be an integer between 1 and 65535",
        ):
            ServerConfig(host="example.com", port="8080", username="user", password="pass")  # type: ignore

    def test_empty_username(self):
        """Test empty username validation."""
        with pytest.raises(ConfigurationError, match="server.username cannot be empty"):
            ServerConfig(host="example.com", port=8080, username="", password="pass")

    def test_empty_password(self):
        """Test empty password validation."""
        with pytest.raises(ConfigurationError, match="server.password cannot be empty"):
            ServerConfig(host="example.com", port=8080, username="user", password="")

    def test_invalid_connection_timeout(self):
        """Test invalid connection timeout validation."""
        with pytest.raises(
            ConfigurationError, match="rtcm_server.connection_timeout must be positive"
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                connection_timeout=0,
            )

    def test_invalid_read_timeout(self):
        """Test invalid read timeout validation."""
        with pytest.raises(
            ConfigurationError, match="rtcm_server.read_timeout must be positive"
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                read_timeout=-5,
            )

    def test_invalid_heartbeat_timeout(self):
        """Test invalid heartbeat timeout validation."""
        with pytest.raises(
            ConfigurationError, match="rtcm_server.heartbeat_timeout must be positive"
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                heartbeat_timeout=0,
            )

    def test_invalid_retry_initial_delay(self):
        """Test invalid retry initial delay validation."""
        with pytest.raises(
            ConfigurationError, match="rtcm_server.retry_initial_delay must be positive"
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                retry_initial_delay=-1,
            )

    def test_invalid_retry_max_delay(self):
        """Test invalid retry max delay validation."""
        with pytest.raises(
            ConfigurationError,
            match="rtcm_server.retry_max_delay must be >= retry_initial_delay",
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                retry_initial_delay=10,
                retry_max_delay=5,
            )

    def test_invalid_retry_multiplier(self):
        """Test invalid retry multiplier validation."""
        with pytest.raises(
            ConfigurationError, match="rtcm_server.retry_multiplier must be > 1.0"
        ):
            ServerConfig(
                host="example.com",
                port=8080,
                username="user",
                password="pass",
                retry_multiplier=0.5,
            )


class TestTCPInputConfig:
    """Test TCP input configuration."""

    def test_default_tcp_config(self):
        """Test default TCP configuration."""
        config = TCPInputConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 5015
        assert config.timeout == 5.0
        assert config.buffer_size == 4096

    def test_valid_tcp_config(self):
        """Test valid TCP configuration."""
        config = TCPInputConfig(host="192.168.1.100", port=8080, timeout=10.0)
        assert config.host == "192.168.1.100"
        assert config.port == 8080
        assert config.timeout == 10.0

    def test_empty_host(self):
        """Test empty host validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.host cannot be empty"
        ):
            TCPInputConfig(host="")

    def test_invalid_port(self):
        """Test invalid port validation."""
        with pytest.raises(
            ConfigurationError,
            match="input.config.port must be an integer between 1 and 65535",
        ):
            TCPInputConfig(port=0)

    def test_negative_timeout(self):
        """Test negative timeout validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.timeout must be positive"
        ):
            TCPInputConfig(timeout=-1.0)


class TestSerialInputConfig:
    """Test serial input configuration."""

    def test_default_serial_config(self):
        """Test default serial configuration."""
        config = SerialInputConfig()
        assert config.port == "/dev/ttyUSB0"
        assert config.baudrate == 115200
        assert config.bytesize == 8
        assert config.parity == "N"
        assert config.stopbits == 1
        assert config.timeout == 1.0
        assert config.rtscts is False
        assert config.xonxoff is False

    def test_valid_serial_config(self):
        """Test valid serial configuration."""
        config = SerialInputConfig(
            port="/dev/ttyS0", baudrate=38400, bytesize=7, parity="E", stopbits=2
        )
        assert config.port == "/dev/ttyS0"
        assert config.baudrate == 38400
        assert config.bytesize == 7
        assert config.parity == "E"
        assert config.stopbits == 2

    def test_empty_port(self):
        """Test empty port validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.port cannot be empty"
        ):
            SerialInputConfig(port="")

    def test_invalid_baudrate(self):
        """Test invalid baudrate validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.baudrate must be one of"
        ):
            SerialInputConfig(baudrate=12345)

    def test_invalid_bytesize(self):
        """Test invalid bytesize validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.bytesize must be one of"
        ):
            SerialInputConfig(bytesize=9)

    def test_invalid_parity(self):
        """Test invalid parity validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.parity must be one of"
        ):
            SerialInputConfig(parity="X")

    def test_invalid_stopbits(self):
        """Test invalid stopbits validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.stopbits must be one of"
        ):
            SerialInputConfig(stopbits=3)

    def test_negative_timeout(self):
        """Test negative timeout validation."""
        with pytest.raises(
            ConfigurationError, match="input.config.timeout must be positive"
        ):
            SerialInputConfig(timeout=-1.0)


class TestInputConfig:
    """Test input configuration."""

    def test_valid_tcp_input_config(self):
        """Test valid TCP input configuration."""
        config = InputConfig(
            source="tcp", config={"host": "127.0.0.1", "port": 5015, "timeout": 5.0}
        )
        assert config.source == "tcp"
        assert config.config["host"] == "127.0.0.1"
        assert config.config["port"] == 5015

    def test_valid_serial_input_config(self):
        """Test valid serial input configuration."""
        config = InputConfig(
            source="serial", config={"port": "/dev/ttyUSB0", "baudrate": 115200}
        )
        assert config.source == "serial"
        assert config.config["port"] == "/dev/ttyUSB0"
        assert config.config["baudrate"] == 115200

    def test_valid_input_sources(self):
        """Test valid input sources."""
        for source in ["tcp", "serial", "usb_serial"]:
            config = InputConfig(
                source=source,
                config=(
                    {"host": "127.0.0.1", "port": 5015}
                    if source == "tcp"
                    else {"port": "/dev/ttyUSB0", "baudrate": 115200}
                ),
            )
            assert config.source == source

    def test_invalid_input_source(self):
        """Test invalid input source validation."""
        with pytest.raises(ConfigurationError, match="input.source must be one of"):
            InputConfig(source="invalid", config={})

    def test_tcp_config_missing_required_field(self):
        """Test TCP config validation with missing required field."""
        with pytest.raises(
            ConfigurationError, match="TCP input configuration missing required fields"
        ):
            InputConfig(source="tcp", config={"host": "127.0.0.1"})  # Missing port

    def test_serial_config_missing_required_field(self):
        """Test serial config validation with missing required field."""
        with pytest.raises(
            ConfigurationError,
            match="Serial input configuration missing required fields",
        ):
            InputConfig(
                source="serial", config={"port": "/dev/ttyUSB0"}
            )  # Missing baudrate

    def test_get_tcp_config(self):
        """Test getting typed TCP configuration."""
        config = InputConfig(
            source="tcp",
            config={"host": "192.168.1.100", "port": 8080, "timeout": 10.0},
        )
        tcp_config = config.get_tcp_config()
        assert isinstance(tcp_config, TCPInputConfig)
        assert tcp_config.host == "192.168.1.100"
        assert tcp_config.port == 8080

    def test_get_serial_config(self):
        """Test getting typed serial configuration."""
        config = InputConfig(
            source="serial", config={"port": "/dev/ttyS0", "baudrate": 38400}
        )
        serial_config = config.get_serial_config()
        assert isinstance(serial_config, SerialInputConfig)
        assert serial_config.port == "/dev/ttyS0"
        assert serial_config.baudrate == 38400

    def test_get_tcp_config_wrong_source(self):
        """Test getting TCP config when source is not TCP."""
        config = InputConfig(
            source="serial", config={"port": "/dev/ttyUSB0", "baudrate": 115200}
        )
        with pytest.raises(
            ConfigurationError, match="Cannot get TCP config when input source is"
        ):
            config.get_tcp_config()

    def test_get_serial_config_wrong_source(self):
        """Test getting serial config when source is not serial."""
        config = InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 5015})
        with pytest.raises(
            ConfigurationError, match="Cannot get serial config when input source is"
        ):
            config.get_serial_config()


class TestMonitoringConfig:
    """Test monitoring configuration."""

    def test_default_monitoring_config(self):
        """Test default monitoring configuration."""
        config = MonitoringConfig()
        assert config.heartbeat_timeout == 30
        assert config.reconnect_delay_base == 1
        assert config.reconnect_max_delay == 60
        assert config.max_reconnect_attempts == 0
        assert config.connection_check_interval == 5

    def test_valid_monitoring_config(self):
        """Test valid monitoring configuration."""
        config = MonitoringConfig(
            heartbeat_timeout=45,
            reconnect_delay_base=2,
            reconnect_max_delay=120,
            max_reconnect_attempts=10,
            connection_check_interval=10,
        )
        assert config.heartbeat_timeout == 45
        assert config.reconnect_delay_base == 2
        assert config.reconnect_max_delay == 120
        assert config.max_reconnect_attempts == 10
        assert config.connection_check_interval == 10

    def test_negative_heartbeat_timeout(self):
        """Test negative heartbeat timeout validation."""
        with pytest.raises(
            ConfigurationError, match="monitoring.heartbeat_timeout must be positive"
        ):
            MonitoringConfig(heartbeat_timeout=-1)

    def test_negative_reconnect_delay_base(self):
        """Test negative reconnect delay base validation."""
        with pytest.raises(
            ConfigurationError, match="monitoring.reconnect_delay_base must be positive"
        ):
            MonitoringConfig(reconnect_delay_base=-1)

    def test_max_delay_less_than_base(self):
        """Test max delay less than base validation."""
        with pytest.raises(
            ConfigurationError,
            match="monitoring.reconnect_max_delay must be >= reconnect_delay_base",
        ):
            MonitoringConfig(reconnect_delay_base=10, reconnect_max_delay=5)

    def test_negative_max_reconnect_attempts(self):
        """Test negative max reconnect attempts validation."""
        with pytest.raises(
            ConfigurationError, match="monitoring.max_reconnect_attempts must be >= 0"
        ):
            MonitoringConfig(max_reconnect_attempts=-1)

    def test_negative_connection_check_interval(self):
        """Test negative connection check interval validation."""
        with pytest.raises(
            ConfigurationError,
            match="monitoring.connection_check_interval must be positive",
        ):
            MonitoringConfig(connection_check_interval=-1)


class TestMetricsConfig:
    """Test metrics configuration."""

    def test_default_metrics_config(self):
        """Test default metrics configuration."""
        config = MetricsConfig()
        assert config.enabled is True
        assert config.host == "0.0.0.0"
        assert config.port == 8080
        assert config.path == "/metrics"

    def test_valid_metrics_config(self):
        """Test valid metrics configuration."""
        config = MetricsConfig(
            enabled=False, host="127.0.0.1", port=9090, path="/custom/metrics"
        )
        assert config.enabled is False
        assert config.host == "127.0.0.1"
        assert config.port == 9090
        assert config.path == "/custom/metrics"

    def test_invalid_port(self):
        """Test invalid port validation."""
        with pytest.raises(
            ConfigurationError,
            match="metrics.port must be an integer between 1 and 65535",
        ):
            MetricsConfig(port=0)

    def test_invalid_path(self):
        """Test invalid path validation."""
        with pytest.raises(
            ConfigurationError, match="metrics.path must start with '/'"
        ):
            MetricsConfig(path="metrics")


class TestLoggingConfig:
    """Test logging configuration."""

    def test_default_logging_config(self):
        """Test default logging configuration."""
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.format == "json"
        assert config.file == "/var/log/sp-rtk-base-relay.log"
        assert config.max_size_mb == 50
        assert config.backup_count == 3

    def test_valid_logging_config(self):
        """Test valid logging configuration."""
        config = LoggingConfig(
            level="DEBUG",
            format="text",
            file="/tmp/test.log",
            max_size_mb=100,
            backup_count=5,
        )
        assert config.level == "DEBUG"
        assert config.format == "text"
        assert config.file == "/tmp/test.log"
        assert config.max_size_mb == 100
        assert config.backup_count == 5

    def test_invalid_level(self):
        """Test invalid log level validation."""
        with pytest.raises(ConfigurationError, match="logging.level must be one of"):
            LoggingConfig(level="INVALID")

    def test_invalid_format(self):
        """Test invalid log format validation."""
        with pytest.raises(ConfigurationError, match="logging.format must be one of"):
            LoggingConfig(format="invalid")

    def test_negative_max_size(self):
        """Test negative max size validation."""
        with pytest.raises(
            ConfigurationError, match="logging.max_size_mb must be positive"
        ):
            LoggingConfig(max_size_mb=-1)

    def test_negative_backup_count(self):
        """Test negative backup count validation."""
        with pytest.raises(
            ConfigurationError, match="logging.backup_count must be >= 0"
        ):
            LoggingConfig(backup_count=-1)


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


class TestConfig:
    """Test complete configuration (v2.0 destinations format)."""

    def test_config_from_dict_minimal(self):
        """Test config creation from minimal v2 dict."""
        data = _v2_config_data()
        config = Config.from_dict(data)
        assert config.input.source == "tcp"
        assert len(config.destinations) == 1
        assert config.destinations[0].name == "surepath"
        assert config.destinations[0].type == "surepath"

    def test_config_from_dict_complete(self):
        """Test config creation from complete v2 dict."""
        data = _v2_config_data(
            input_data={
                "source": "serial",
                "config": {"port": "/dev/ttyS0", "baudrate": 38400},
            },
            metrics={"enabled": False, "port": 9090},
            logging={"level": "DEBUG", "format": "text"},
            service={"daemon": True, "user": "myuser"},
        )
        config = Config.from_dict(data)
        assert config.input.source == "serial"
        assert config.input.config["port"] == "/dev/ttyS0"
        assert config.input.config["baudrate"] == 38400
        assert config.metrics.enabled is False
        assert config.logging.level == "DEBUG"
        assert config.service.daemon is True

    def test_config_from_dict_missing_destinations(self):
        """Test config creation with missing destinations section."""
        data = {
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}}
        }
        with pytest.raises(
            ConfigurationError, match="destinations list is required"
        ):
            Config.from_dict(data)

    def test_config_from_dict_missing_input_source(self):
        """Test config creation with missing input.source."""
        data = _v2_config_data(
            input_data={"config": {"host": "127.0.0.1", "port": 5015}},
        )
        with pytest.raises(ConfigurationError, match="input.source is required"):
            Config.from_dict(data)

    def test_config_from_dict_missing_input_config(self):
        """Test config creation with missing input.config."""
        data = _v2_config_data(input_data={"source": "tcp"})
        with pytest.raises(ConfigurationError, match="input.config is required"):
            Config.from_dict(data)

    def test_config_from_dict_old_server_format_rejected(self):
        """Test that old v1.x server: format is rejected (DR-4)."""
        data = {
            "server": {
                "host": "example.com",
                "port": 8080,
                "username": "user",
                "password": "pass",
            },
            "input": {"source": "tcp", "config": {"host": "127.0.0.1", "port": 5015}},
            "destinations": [_v2_surepath_dest()],
        }
        with pytest.raises(
            ConfigurationError, match="Old v1.x configuration format detected"
        ):
            Config.from_dict(data)

    def test_config_from_dict_old_input_format_rejected(self):
        """Test that old input type/tcp/serial format is rejected."""
        data = _v2_config_data(
            input_data={
                "type": "tcp",
                "tcp": {"host": "192.168.1.1", "port": 9090},
            },
        )
        with pytest.raises(
            ConfigurationError, match="Old input configuration format detected"
        ):
            Config.from_dict(data)

    def test_config_from_dict_invalid_format(self):
        """Test config creation with invalid format."""
        with pytest.raises(ConfigurationError, match="Invalid configuration format"):
            Config.from_dict("not a dict")  # type: ignore


class TestConfigManager:
    """Test configuration manager."""

    def test_generate_default_config(self):
        """Test default configuration generation (v2 format)."""
        config_yaml = ConfigManager.generate_default_config()
        data = yaml.safe_load(config_yaml)

        assert "input" in data
        assert "destinations" in data
        assert "metrics" in data
        assert "logging" in data
        assert "service" in data
        assert "server" not in data  # v1 key removed

        assert data["input"]["source"] == "tcp"
        assert data["input"]["config"]["host"] == "127.0.0.1"
        assert len(data["destinations"]) == 2
        assert data["destinations"][0]["name"] == "surepath"
        assert data["destinations"][0]["type"] == "surepath"

    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="""
input:
  source: "tcp"
  config:
    host: "127.0.0.1"
    port: 5015
destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: "test.example.com"
      port: 50010
      username: "testuser"
      password: "testpass"
""",
    )
    @patch("pathlib.Path.exists")
    def test_load_config_from_file(self, mock_exists: Any, mock_file: Any) -> None:
        """Test loading configuration from file (v2 format)."""
        mock_exists.return_value = True

        config = ConfigManager.load_config("/test/config.yaml")
        assert len(config.destinations) == 1
        from sp_rtk_base_relay.config import SurePathDestinationConfig
        assert isinstance(config.destinations[0].config, SurePathDestinationConfig)
        assert config.destinations[0].config.host == "test.example.com"

    @patch.dict(os.environ, {"SP_DEST_SUREPATH_HOST": "env.example.com", "SP_DEST_SUREPATH_PORT": "9090"})
    @patch(
        "builtins.open",
        new_callable=mock_open,
        read_data="""
input:
  source: "tcp"
  config:
    host: "127.0.0.1"
    port: 5015
destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: "file.example.com"
      port: 50010
      username: "testuser"
      password: "testpass"
""",
    )
    @patch("pathlib.Path.exists")
    def test_env_overrides(self, mock_exists: Any, mock_file: Any) -> None:
        """Test dynamic per-destination environment variable overrides."""
        mock_exists.return_value = True

        config = ConfigManager.load_config("/test/config.yaml")
        from sp_rtk_base_relay.config import SurePathDestinationConfig
        assert isinstance(config.destinations[0].config, SurePathDestinationConfig)
        assert config.destinations[0].config.host == "env.example.com"
        assert config.destinations[0].config.port == 9090

    def test_env_overrides_data_types(self):
        """Test environment variable type conversions."""
        data = _v2_config_data(
            metrics={"enabled": False, "port": 8080},
        )

        with patch.dict(
            os.environ, {"SP_METRICS_ENABLED": "true", "SP_METRICS_PORT": "9090"}
        ):
            result = ConfigManager._apply_env_overrides(data)  # type: ignore[attr-defined]
            assert result["metrics"]["enabled"] is True
            assert result["metrics"]["port"] == 9090

    def test_load_config_file_not_found(self):
        """Test loading non-existent configuration file."""
        with pytest.raises(ConfigurationError, match="Configuration file not found"):
            ConfigManager.load_config("/nonexistent/config.yaml")

    @patch("builtins.open", new_callable=mock_open, read_data="invalid: yaml: content:")
    @patch("pathlib.Path.exists")
    def test_load_config_invalid_yaml(self, mock_exists: Any, mock_file: Any) -> None:
        """Test loading invalid YAML configuration."""
        mock_exists.return_value = True

        with pytest.raises(ConfigurationError, match="Invalid YAML syntax"):
            ConfigManager.load_config("/test/config.yaml")

    @patch("builtins.open", new_callable=mock_open, read_data="[]")
    @patch("pathlib.Path.exists")
    def test_load_config_not_dict(self, mock_exists: Any, mock_file: Any) -> None:
        """Test loading configuration that's not a dictionary."""
        mock_exists.return_value = True

        with pytest.raises(
            ConfigurationError,
            match="Configuration file must contain a YAML dictionary",
        ):
            ConfigManager.load_config("/test/config.yaml")

    def test_validate_config_file(self):
        """Test configuration file validation (v2 format)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_v2_config_data(), f)
            config_path = f.name

        try:
            ConfigManager.validate_config_file(config_path)
        finally:
            os.unlink(config_path)

    def test_validate_invalid_config_file(self):
        """Test validation of invalid configuration file (v2 format)."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                _v2_config_data(
                    destinations=[_v2_surepath_dest(host="")]  # Invalid empty host
                ),
                f,
            )
            config_path = f.name

        try:
            with pytest.raises(ConfigurationError):
                ConfigManager.validate_config_file(config_path)
        finally:
            os.unlink(config_path)


if __name__ == "__main__":
    pytest.main([__file__])
