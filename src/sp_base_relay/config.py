"""Configuration management for SP-Base-Relay.

This module provides comprehensive configuration management including:
- YAML configuration file parsing
- Configuration validation with detailed error messages
- Environment variable override support
- Default configuration generation
"""

# pyright: reportUnnecessaryIsInstance=false
# Note: isinstance checks are necessary for runtime validation of YAML-loaded data

import os
import yaml
from pathlib import Path
from typing import Any, cast
from dataclasses import dataclass, field

from .exceptions import ConfigurationError


@dataclass
class RTCMServerConfig:
    """RTCM server configuration."""

    host: str
    port: int
    username: str
    password: str
    connection_timeout: int = 10
    read_timeout: int = 30
    heartbeat_timeout: int = 30
    retry_initial_delay: int = 15
    retry_max_delay: int = 60
    retry_multiplier: float = 2.0

    def __post_init__(self) -> None:
        """Validate RTCM server configuration after initialization."""
        if not self.host:
            raise ConfigurationError("rtcm_server.host cannot be empty")

        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "rtcm_server.port must be an integer between 1 and 65535",
                config_key="rtcm_server.port",
            )

        if not self.username:
            raise ConfigurationError("rtcm_server.username cannot be empty")

        if not self.password:
            raise ConfigurationError("rtcm_server.password cannot be empty")

        if self.connection_timeout <= 0:
            raise ConfigurationError(
                "rtcm_server.connection_timeout must be positive",
                config_key="rtcm_server.connection_timeout",
            )

        if self.read_timeout <= 0:
            raise ConfigurationError(
                "rtcm_server.read_timeout must be positive",
                config_key="rtcm_server.read_timeout",
            )

        if self.heartbeat_timeout <= 0:
            raise ConfigurationError(
                "rtcm_server.heartbeat_timeout must be positive",
                config_key="rtcm_server.heartbeat_timeout",
            )

        if self.retry_initial_delay <= 0:
            raise ConfigurationError(
                "rtcm_server.retry_initial_delay must be positive",
                config_key="rtcm_server.retry_initial_delay",
            )

        if self.retry_max_delay < self.retry_initial_delay:
            raise ConfigurationError(
                "rtcm_server.retry_max_delay must be >= retry_initial_delay",
                config_key="rtcm_server.retry_max_delay",
            )

        if self.retry_multiplier <= 1.0:
            raise ConfigurationError(
                "rtcm_server.retry_multiplier must be > 1.0",
                config_key="rtcm_server.retry_multiplier",
            )


# Keep ServerConfig as alias for backward compatibility
ServerConfig = RTCMServerConfig


@dataclass
class TCPInputConfig:
    """TCP input source configuration."""

    host: str = "127.0.0.1"
    port: int = 5015
    timeout: float = 5.0
    buffer_size: int = 4096

    def __post_init__(self) -> None:
        """Validate TCP input configuration."""
        if not self.host:
            raise ConfigurationError("input.config.host cannot be empty")

        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "input.config.port must be an integer between 1 and 65535",
                config_key="input.config.port",
            )

        if self.timeout <= 0:
            raise ConfigurationError(
                "input.config.timeout must be positive",
                config_key="input.config.timeout",
            )


@dataclass
class SerialInputConfig:
    """Serial input source configuration."""

    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: float = 1
    timeout: float = 1.0
    rtscts: bool = False
    xonxoff: bool = False

    def __post_init__(self) -> None:
        """Validate serial input configuration."""
        valid_bytesize = {5, 6, 7, 8}
        valid_parity = {"N", "E", "O", "M", "S"}
        valid_stopbits = {1, 1.5, 2}
        valid_baudrates = {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600}

        if not self.port:
            raise ConfigurationError("input.config.port cannot be empty")

        if self.baudrate not in valid_baudrates:
            raise ConfigurationError(
                f"input.config.baudrate must be one of: {valid_baudrates}",
                config_key="input.config.baudrate",
            )

        if self.bytesize not in valid_bytesize:
            raise ConfigurationError(
                f"input.config.bytesize must be one of: {valid_bytesize}",
                config_key="input.config.bytesize",
            )

        if self.parity not in valid_parity:
            raise ConfigurationError(
                f"input.config.parity must be one of: {valid_parity}",
                config_key="input.config.parity",
            )

        if self.stopbits not in valid_stopbits:
            raise ConfigurationError(
                f"input.config.stopbits must be one of: {valid_stopbits}",
                config_key="input.config.stopbits",
            )

        if self.timeout <= 0:
            raise ConfigurationError(
                "input.config.timeout must be positive",
                config_key="input.config.timeout",
            )


@dataclass
class InputConfig:
    """Input source configuration using discriminated union pattern.

    Only ONE source type is active at a time, specified by the 'source' field.
    The 'config' field contains source-specific configuration parameters.
    """

    source: str  # One of: tcp, serial, usb_serial
    config: dict[str, Any]  # Source-specific configuration

    def __post_init__(self) -> None:
        """Validate input configuration."""
        valid_sources = {"tcp", "serial", "usb_serial"}

        if self.source not in valid_sources:
            raise ConfigurationError(
                f"input.source must be one of: {valid_sources}",
                config_key="input.source",
            )

        # Validate source-specific configuration
        if self.source == "tcp":
            self._validate_tcp_config()
        elif self.source in ("serial", "usb_serial"):
            self._validate_serial_config()

    def _validate_tcp_config(self) -> None:
        """Validate TCP-specific configuration."""
        required = {"host", "port"}
        missing = required - set(self.config.keys())
        if missing:
            raise ConfigurationError(
                f"TCP input configuration missing required fields: {missing}",
                config_key="input.config",
            )

        # Create TCPInputConfig to validate
        try:
            TCPInputConfig(**self.config)
        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(
                f"Invalid TCP input configuration: {e}", config_key="input.config"
            )

    def _validate_serial_config(self) -> None:
        """Validate serial-specific configuration."""
        required = {"port", "baudrate"}
        missing = required - set(self.config.keys())
        if missing:
            raise ConfigurationError(
                f"Serial input configuration missing required fields: {missing}",
                config_key="input.config",
            )

        # Create SerialInputConfig to validate
        try:
            SerialInputConfig(**self.config)
        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(
                f"Invalid serial input configuration: {e}", config_key="input.config"
            )

    def get_tcp_config(self) -> TCPInputConfig:
        """Get typed TCP configuration.

        Returns:
            TCPInputConfig instance with validated configuration

        Raises:
            ConfigurationError: If current source is not TCP
        """
        if self.source != "tcp":
            raise ConfigurationError(
                f"Cannot get TCP config when input source is '{self.source}'",
                config_key="input.source",
            )
        return TCPInputConfig(**self.config)

    def get_serial_config(self) -> SerialInputConfig:
        """Get typed serial configuration.

        Returns:
            SerialInputConfig instance with validated configuration

        Raises:
            ConfigurationError: If current source is not serial/usb_serial
        """
        if self.source not in ("serial", "usb_serial"):
            raise ConfigurationError(
                f"Cannot get serial config when input source is '{self.source}'",
                config_key="input.source",
            )
        return SerialInputConfig(**self.config)


@dataclass
class MonitoringConfig:
    """Connection monitoring configuration."""

    heartbeat_timeout: int = 30
    reconnect_delay_base: int = 1
    reconnect_max_delay: int = 60
    max_reconnect_attempts: int = 0  # 0 = unlimited
    connection_check_interval: int = 5

    def __post_init__(self) -> None:
        """Validate monitoring configuration."""
        if self.heartbeat_timeout <= 0:
            raise ConfigurationError(
                "monitoring.heartbeat_timeout must be positive",
                config_key="monitoring.heartbeat_timeout",
            )

        if self.reconnect_delay_base <= 0:
            raise ConfigurationError(
                "monitoring.reconnect_delay_base must be positive",
                config_key="monitoring.reconnect_delay_base",
            )

        if self.reconnect_max_delay < self.reconnect_delay_base:
            raise ConfigurationError(
                "monitoring.reconnect_max_delay must be >= reconnect_delay_base",
                config_key="monitoring.reconnect_max_delay",
            )

        if self.max_reconnect_attempts < 0:
            raise ConfigurationError(
                "monitoring.max_reconnect_attempts must be >= 0",
                config_key="monitoring.max_reconnect_attempts",
            )

        if self.connection_check_interval <= 0:
            raise ConfigurationError(
                "monitoring.connection_check_interval must be positive",
                config_key="monitoring.connection_check_interval",
            )


@dataclass
class MetricsConfig:
    """Metrics configuration."""

    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/metrics"

    def __post_init__(self) -> None:
        """Validate metrics configuration."""
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "metrics.port must be an integer between 1 and 65535",
                config_key="metrics.port",
            )

        if not self.path.startswith("/"):
            raise ConfigurationError(
                "metrics.path must start with '/'", config_key="metrics.path"
            )


@dataclass
class PipelineRestartConfig:
    """Pipeline automatic restart configuration."""

    enabled: bool = True
    max_attempts: int = 3
    initial_delay: int = 2
    max_delay: int = 60
    backoff_multiplier: float = 2.0
    reset_after_success: int = 300

    def __post_init__(self) -> None:
        """Validate pipeline restart configuration."""
        if self.max_attempts < 0:
            raise ConfigurationError(
                "pipeline.restart.max_attempts must be >= 0",
                config_key="pipeline.restart.max_attempts",
            )

        if self.initial_delay <= 0:
            raise ConfigurationError(
                "pipeline.restart.initial_delay must be positive",
                config_key="pipeline.restart.initial_delay",
            )

        if self.max_delay < self.initial_delay:
            raise ConfigurationError(
                "pipeline.restart.max_delay must be >= initial_delay",
                config_key="pipeline.restart.max_delay",
            )

        if self.backoff_multiplier <= 1.0:
            raise ConfigurationError(
                "pipeline.restart.backoff_multiplier must be > 1.0",
                config_key="pipeline.restart.backoff_multiplier",
            )

        if self.reset_after_success <= 0:
            raise ConfigurationError(
                "pipeline.restart.reset_after_success must be positive",
                config_key="pipeline.restart.reset_after_success",
            )


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "json"
    file: str | None = "/var/log/sp-base-relay.log"
    max_size_mb: int = 50
    backup_count: int = 3

    def __post_init__(self) -> None:
        """Validate logging configuration."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        valid_formats = {"json", "text"}

        if self.level not in valid_levels:
            raise ConfigurationError(
                f"logging.level must be one of: {valid_levels}",
                config_key="logging.level",
            )

        if self.format not in valid_formats:
            raise ConfigurationError(
                f"logging.format must be one of: {valid_formats}",
                config_key="logging.format",
            )

        if self.max_size_mb <= 0:
            raise ConfigurationError(
                "logging.max_size_mb must be positive", config_key="logging.max_size_mb"
            )

        if self.backup_count < 0:
            raise ConfigurationError(
                "logging.backup_count must be >= 0", config_key="logging.backup_count"
            )


@dataclass
class ServiceConfig:
    """Service configuration."""

    daemon: bool = False
    pid_file: str = "/var/run/sp-base-relay.pid"
    user: str = "sp-base-relay"
    group: str = "sp-base-relay"


@dataclass
class Config:
    """Complete SP-Base-Relay configuration."""

    server: ServerConfig
    input: InputConfig
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    pipeline_restart: PipelineRestartConfig = field(default_factory=PipelineRestartConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create configuration from dictionary data.

        Args:
            data: dictionary containing configuration data

        Returns:
            Configuration instance

        Raises:
            ConfigurationError: If configuration is invalid
        """
        try:
            # Validate input type
            if not isinstance(data, dict):
                raise ConfigurationError(
                    "Invalid configuration format: expected dictionary"
                )

            # Parse server configuration (required)
            if "server" not in data:
                raise ConfigurationError("server configuration is required")

            server_data = data["server"]
            server = ServerConfig(
                host=server_data.get("host", ""),
                port=server_data.get("port", 50010),
                username=server_data.get("username", ""),
                password=server_data.get("password", ""),
                connection_timeout=server_data.get("connection_timeout", 10),
                read_timeout=server_data.get("read_timeout", 30),
                heartbeat_timeout=server_data.get("heartbeat_timeout", 30),
                retry_initial_delay=server_data.get("retry_initial_delay", 15),
                retry_max_delay=server_data.get("retry_max_delay", 60),
                retry_multiplier=server_data.get("retry_multiplier", 2.0),
            )

            # Parse input configuration (NEW FORMAT)
            input_data = data.get("input", {})

            # Check for old format and reject it
            if "type" in input_data or "tcp" in input_data or "serial" in input_data:
                raise ConfigurationError(
                    "Old configuration format detected. "
                    "Please update your config file to use 'source' and 'config' instead of 'type', 'tcp', and 'serial'. "
                    "Example:\n"
                    "  input:\n"
                    "    source: tcp\n"
                    "    config:\n"
                    "      host: 127.0.0.1\n"
                    "      port: 5015",
                    config_key="input",
                )

            # Validate new format structure
            if "source" not in input_data:
                raise ConfigurationError(
                    "input.source is required (must be one of: tcp, serial, usb_serial)",
                    config_key="input.source",
                )

            if "config" not in input_data:
                raise ConfigurationError(
                    "input.config is required (source-specific configuration parameters)",
                    config_key="input.config",
                )

            input_config = InputConfig(
                source=input_data["source"], config=input_data["config"]
            )

            # Parse monitoring configuration
            monitoring_data = data.get("monitoring", {})
            monitoring = MonitoringConfig(**monitoring_data)

            # Parse metrics configuration
            metrics_data = data.get("metrics", {})
            metrics = MetricsConfig(**metrics_data)

            # Parse pipeline restart configuration
            pipeline_data = data.get("pipeline", {})
            restart_data = pipeline_data.get("restart", {})
            pipeline_restart = PipelineRestartConfig(**restart_data)

            # Parse logging configuration
            logging_data = data.get("logging", {})
            logging_config = LoggingConfig(**logging_data)

            # Parse service configuration
            service_data = data.get("service", {})
            service = ServiceConfig(**service_data)

            return cls(
                server=server,
                input=input_config,
                monitoring=monitoring,
                metrics=metrics,
                pipeline_restart=pipeline_restart,
                logging=logging_config,
                service=service,
            )

        except Exception as e:
            if isinstance(e, ConfigurationError):
                raise
            raise ConfigurationError(f"Invalid configuration format: {e}")


class ConfigManager:
    """Configuration manager for SP-Base-Relay."""

    DEFAULT_CONFIG_LOCATIONS = [
        "/etc/sp-base-relay/config.yaml",
        "~/.config/sp-base-relay/config.yaml",
        "./config.yaml",
    ]

    ENV_PREFIX = "SP_"

    @classmethod
    def load_config(
        cls, config_path: str | None = None, apply_env_overrides: bool = True
    ) -> Config:
        """Load configuration from file and environment variables.

        Args:
            config_path: Optional path to configuration file
            apply_env_overrides: Whether to apply environment variable overrides

        Returns:
            Loaded and validated configuration

        Raises:
            ConfigurationError: If configuration cannot be loaded or is invalid
        """
        # Determine configuration file path
        if config_path:
            config_file = Path(config_path)
        else:
            # Check environment variable
            env_config_path = os.getenv(f"{cls.ENV_PREFIX}BASE_RELAY_CONFIG")
            if env_config_path:
                config_file = Path(env_config_path)
            else:
                # Find first existing default location
                config_file = None
                for location in cls.DEFAULT_CONFIG_LOCATIONS:
                    path = Path(location).expanduser()
                    if path.exists():
                        config_file = path
                        break

                if not config_file:
                    raise ConfigurationError(
                        "No configuration file found",
                        details=f"Searched locations: {cls.DEFAULT_CONFIG_LOCATIONS}",
                    )

        # Load configuration file
        try:
            with open(config_file, "r") as f:
                raw_data = yaml.safe_load(f)
        except FileNotFoundError:
            raise ConfigurationError(
                f"Configuration file not found: {config_file}",
                config_path=str(config_file),
            )
        except yaml.YAMLError as e:
            raise ConfigurationError(
                "Invalid YAML syntax in configuration file",
                config_path=str(config_file),
                details=str(e),
            )
        except Exception as e:
            raise ConfigurationError(
                f"Error reading configuration file: {e}", config_path=str(config_file)
            )

        # Cast raw_data to proper type to fix Pylance warnings
        data = cast(dict[str, Any], raw_data)

        if not isinstance(raw_data, dict):
            raise ConfigurationError(
                "Configuration file must contain a YAML dictionary",
                config_path=str(config_file),
            )

        # Apply environment variable overrides
        if apply_env_overrides:
            data = cls._apply_env_overrides(data)

        # Create configuration object
        try:
            config = Config.from_dict(data)
            return config
        except ConfigurationError as e:
            if hasattr(e, "config_path"):
                e.config_path = str(config_file)
            raise

    @classmethod
    def _apply_env_overrides(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Apply environment variable overrides to configuration data.

        Args:
            data: Configuration data dictionary

        Returns:
            Configuration data with environment overrides applied
        """
        # Environment variable mappings (updated for new format)
        env_mappings = {
            f"{cls.ENV_PREFIX}RTCM_HOST": ("server", "host"),
            f"{cls.ENV_PREFIX}RTCM_PORT": ("server", "port"),
            f"{cls.ENV_PREFIX}RTCM_USERNAME": ("server", "username"),
            f"{cls.ENV_PREFIX}RTCM_PASSWORD": ("server", "password"),
            f"{cls.ENV_PREFIX}RTCM_CONNECTION_TIMEOUT": (
                "server",
                "connection_timeout",
            ),
            f"{cls.ENV_PREFIX}RTCM_READ_TIMEOUT": ("server", "read_timeout"),
            f"{cls.ENV_PREFIX}RTCM_HEARTBEAT_TIMEOUT": ("server", "heartbeat_timeout"),
            f"{cls.ENV_PREFIX}RTCM_RETRY_INITIAL_DELAY": (
                "server",
                "retry_initial_delay",
            ),
            f"{cls.ENV_PREFIX}RTCM_RETRY_MAX_DELAY": ("server", "retry_max_delay"),
            f"{cls.ENV_PREFIX}RTCM_RETRY_MULTIPLIER": ("server", "retry_multiplier"),
            f"{cls.ENV_PREFIX}INPUT_SOURCE": ("input", "source"),
            f"{cls.ENV_PREFIX}INPUT_TCP_HOST": ("input", "config", "host"),
            f"{cls.ENV_PREFIX}INPUT_TCP_PORT": ("input", "config", "port"),
            f"{cls.ENV_PREFIX}INPUT_TCP_TIMEOUT": ("input", "config", "timeout"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_PORT": ("input", "config", "port"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_BAUDRATE": ("input", "config", "baudrate"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_BYTESIZE": ("input", "config", "bytesize"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_PARITY": ("input", "config", "parity"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_STOPBITS": ("input", "config", "stopbits"),
            f"{cls.ENV_PREFIX}INPUT_SERIAL_TIMEOUT": ("input", "config", "timeout"),
            f"{cls.ENV_PREFIX}HEARTBEAT_TIMEOUT": ("monitoring", "heartbeat_timeout"),
            f"{cls.ENV_PREFIX}RECONNECT_MAX_DELAY": (
                "monitoring",
                "reconnect_max_delay",
            ),
            f"{cls.ENV_PREFIX}METRICS_ENABLED": ("metrics", "enabled"),
            f"{cls.ENV_PREFIX}METRICS_PORT": ("metrics", "port"),
            f"{cls.ENV_PREFIX}LOG_LEVEL": ("logging", "level"),
            f"{cls.ENV_PREFIX}LOG_FORMAT": ("logging", "format"),
        }

        for env_var, config_path in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                # Navigate to the nested configuration
                current = data
                for key in config_path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]

                # Convert value to appropriate type
                final_key = config_path[-1]
                if final_key in [
                    "port",
                    "baudrate",
                    "bytesize",
                    "heartbeat_timeout",
                    "reconnect_max_delay",
                    "metrics_port",
                    "connection_timeout",
                    "read_timeout",
                    "retry_initial_delay",
                    "retry_max_delay",
                ]:
                    try:
                        current[final_key] = int(env_value)
                    except ValueError:
                        pass  # Keep original value if conversion fails
                elif final_key in ["retry_multiplier", "timeout", "stopbits"]:
                    try:
                        current[final_key] = float(env_value)
                    except ValueError:
                        pass  # Keep original value if conversion fails
                elif final_key in ["enabled", "rtscts", "xonxoff"]:
                    current[final_key] = env_value.lower() in ("true", "1", "yes", "on")
                else:
                    current[final_key] = env_value

        return data

    @classmethod
    def generate_default_config(cls) -> str:
        """Generate default configuration file content.

        Returns:
            Default configuration as YAML string
        """
        default_config = {
            "server": {
                "host": "rtcm.example.com",
                "port": 50010,
                "username": "your_username",
                "password": "your_password",
                "connection_timeout": 10,
                "read_timeout": 30,
                "heartbeat_timeout": 30,
                "retry_initial_delay": 15,
                "retry_max_delay": 60,
                "retry_multiplier": 2.0,
            },
            "input": {
                "source": "tcp",
                "config": {
                    "host": "127.0.0.1",
                    "port": 5015,
                    "timeout": 5.0,
                    "buffer_size": 4096,
                },
            },
            "monitoring": {
                "heartbeat_timeout": 30,
                "reconnect_delay_base": 1,
                "reconnect_max_delay": 60,
                "max_reconnect_attempts": 0,
                "connection_check_interval": 5,
            },
            "metrics": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8080,
                "path": "/metrics",
            },
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": "/var/log/sp-base-relay.log",
                "max_size_mb": 50,
                "backup_count": 3,
            },
            "service": {
                "daemon": False,
                "pid_file": "/var/run/sp-base-relay.pid",
                "user": "sp-base-relay",
                "group": "sp-base-relay",
            },
        }

        return yaml.dump(default_config, default_flow_style=False, indent=2)

    @classmethod
    def validate_config_file(cls, config_path: str) -> None:
        """Validate configuration file without loading it.

        Args:
            config_path: Path to configuration file

        Raises:
            ConfigurationError: If configuration is invalid
        """
        try:
            cls.load_config(config_path, apply_env_overrides=False)
        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(f"Unexpected error validating configuration: {e}")
