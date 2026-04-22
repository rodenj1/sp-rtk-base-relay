"""Configuration management for SP-Base-Relay.

This module provides comprehensive configuration management including:
- YAML configuration file parsing
- Configuration validation with detailed error messages
- Environment variable override support
- Default configuration generation
"""

# pyright: reportUnnecessaryIsInstance=false
# Note: isinstance checks are necessary for runtime validation of YAML-loaded data

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import yaml

if TYPE_CHECKING:
    from .core.message_filter import FilterConfig

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
        valid_sources = {"tcp", "serial", "usb_serial", "bluetooth"}

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
    file: str | None = "/var/log/sp-rtk-base-relay.log"
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
    pid_file: str = "/var/run/sp-rtk-base-relay.pid"
    user: str = "sp-rtk-base-relay"
    group: str = "sp-rtk-base-relay"


# ============================================================================
# v2.0 Destination Configuration Dataclasses
# ============================================================================

VALID_DESTINATION_TYPES = {"surepath", "ntrip", "tcp_server"}


@dataclass
class DestinationFilterConfig:
    """Filter configuration parsed from YAML destination filter block.

    Bridges the YAML config format to the frozen FilterConfig dataclass.
    """

    mode: Literal["pass_all", "allowlist", "blocklist"] = "pass_all"
    message_ids: list[int] = field(default_factory=lambda: list[int]())

    def __post_init__(self) -> None:
        """Validate filter configuration."""
        valid_modes = {"pass_all", "allowlist", "blocklist"}
        if self.mode not in valid_modes:
            raise ConfigurationError(
                f"filter.mode must be one of: {valid_modes}",
                config_key="filter.mode",
            )
        if self.mode == "pass_all" and self.message_ids:
            raise ConfigurationError(
                "filter.message_ids must be empty when mode is 'pass_all'",
                config_key="filter.message_ids",
            )
        if self.mode in ("allowlist", "blocklist") and not self.message_ids:
            raise ConfigurationError(
                f"filter.message_ids is required when mode is '{self.mode}'",
                config_key="filter.message_ids",
            )

    def to_filter_config(self) -> FilterConfig:
        """Convert to frozen FilterConfig for use in MessageFilter.

        Returns:
            FilterConfig instance matching the configured mode.
        """
        from .core.message_filter import FilterConfig as _FilterConfig

        if self.mode == "pass_all":
            return _FilterConfig.pass_all()
        elif self.mode == "allowlist":
            return _FilterConfig.allowlist(self.message_ids)
        else:
            return _FilterConfig.blocklist(self.message_ids)


@dataclass
class SurePathDestinationConfig:
    """Sure-Path destination-specific configuration."""

    host: str = ""
    port: int = 50010
    username: str = ""
    password: str = ""
    connection_timeout: int = 10
    read_timeout: int = 30
    heartbeat_timeout: int = 30
    retry_initial_delay: int = 15
    retry_max_delay: int = 60
    retry_multiplier: float = 2.0

    def __post_init__(self) -> None:
        """Validate Sure-Path destination configuration."""
        if not self.host:
            raise ConfigurationError(
                "destinations[surepath].config.host cannot be empty",
                config_key="config.host",
            )
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "destinations[surepath].config.port must be 1-65535",
                config_key="config.port",
            )
        if not self.username:
            raise ConfigurationError(
                "destinations[surepath].config.username cannot be empty",
                config_key="config.username",
            )
        if not self.password:
            raise ConfigurationError(
                "destinations[surepath].config.password cannot be empty",
                config_key="config.password",
            )
        if self.connection_timeout <= 0:
            raise ConfigurationError(
                "destinations[surepath].config.connection_timeout must be positive",
                config_key="config.connection_timeout",
            )
        if self.read_timeout <= 0:
            raise ConfigurationError(
                "destinations[surepath].config.read_timeout must be positive",
                config_key="config.read_timeout",
            )
        if self.heartbeat_timeout <= 0:
            raise ConfigurationError(
                "destinations[surepath].config.heartbeat_timeout must be positive",
                config_key="config.heartbeat_timeout",
            )
        if self.retry_initial_delay <= 0:
            raise ConfigurationError(
                "destinations[surepath].config.retry_initial_delay must be positive",
                config_key="config.retry_initial_delay",
            )
        if self.retry_max_delay < self.retry_initial_delay:
            raise ConfigurationError(
                "destinations[surepath].config.retry_max_delay "
                "must be >= retry_initial_delay",
                config_key="config.retry_max_delay",
            )
        if self.retry_multiplier <= 1.0:
            raise ConfigurationError(
                "destinations[surepath].config.retry_multiplier must be > 1.0",
                config_key="config.retry_multiplier",
            )

    def to_rtcm_server_config(self) -> RTCMServerConfig:
        """Convert to RTCMServerConfig for use with RTCMClient.

        Returns:
            RTCMServerConfig with matching field values.
        """
        return RTCMServerConfig(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            connection_timeout=self.connection_timeout,
            read_timeout=self.read_timeout,
            heartbeat_timeout=self.heartbeat_timeout,
            retry_initial_delay=self.retry_initial_delay,
            retry_max_delay=self.retry_max_delay,
            retry_multiplier=self.retry_multiplier,
        )


@dataclass
class NtripDestinationConfig:
    """NTRIP destination-specific configuration."""

    caster: str = ""
    port: int = 2101
    mountpoint: str = ""
    password: str = ""
    username: str = ""
    version: str = "2.0"
    connection_timeout: int = 15
    retry_initial_delay: int = 10
    retry_max_delay: int = 120
    retry_multiplier: float = 2.0

    def __post_init__(self) -> None:
        """Validate NTRIP destination configuration."""
        if not self.caster:
            raise ConfigurationError(
                "destinations[ntrip].config.caster cannot be empty",
                config_key="config.caster",
            )
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "destinations[ntrip].config.port must be 1-65535",
                config_key="config.port",
            )
        if not self.mountpoint:
            raise ConfigurationError(
                "destinations[ntrip].config.mountpoint cannot be empty",
                config_key="config.mountpoint",
            )
        if not self.password:
            raise ConfigurationError(
                "destinations[ntrip].config.password cannot be empty",
                config_key="config.password",
            )
        valid_versions = {"1.0", "2.0"}
        if self.version not in valid_versions:
            raise ConfigurationError(
                f"destinations[ntrip].config.version must be one of: {valid_versions}",
                config_key="config.version",
            )
        if self.connection_timeout <= 0:
            raise ConfigurationError(
                "destinations[ntrip].config.connection_timeout must be positive",
                config_key="config.connection_timeout",
            )
        if self.retry_initial_delay <= 0:
            raise ConfigurationError(
                "destinations[ntrip].config.retry_initial_delay must be positive",
                config_key="config.retry_initial_delay",
            )
        if self.retry_max_delay < self.retry_initial_delay:
            raise ConfigurationError(
                "destinations[ntrip].config.retry_max_delay "
                "must be >= retry_initial_delay",
                config_key="config.retry_max_delay",
            )
        if self.retry_multiplier <= 1.0:
            raise ConfigurationError(
                "destinations[ntrip].config.retry_multiplier must be > 1.0",
                config_key="config.retry_multiplier",
            )


@dataclass
class TcpServerDestinationConfig:
    """TCP server destination-specific configuration."""

    host: str = "0.0.0.0"
    port: int = 5016
    max_clients: int = 10

    def __post_init__(self) -> None:
        """Validate TCP server destination configuration."""
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            raise ConfigurationError(
                "destinations[tcp_server].config.port must be 1-65535",
                config_key="config.port",
            )
        if self.max_clients < 1:
            raise ConfigurationError(
                "destinations[tcp_server].config.max_clients must be >= 1",
                config_key="config.max_clients",
            )


# Type alias for destination-specific configs
DestinationSpecificConfig = (
    SurePathDestinationConfig | NtripDestinationConfig | TcpServerDestinationConfig
)


@dataclass
class DestinationConfig:
    """Configuration for a single destination in the destinations list."""

    name: str
    type: str
    enabled: bool
    filter: DestinationFilterConfig
    config: DestinationSpecificConfig

    def __post_init__(self) -> None:
        """Validate destination configuration."""
        if not self.name:
            raise ConfigurationError(
                "destination.name cannot be empty",
                config_key="destinations[].name",
            )
        if not self.name.replace("_", "").replace("-", "").isalnum():
            raise ConfigurationError(
                f"destination.name '{self.name}' must be alphanumeric "
                "(with underscores/hyphens allowed)",
                config_key="destinations[].name",
            )
        if self.type not in VALID_DESTINATION_TYPES:
            raise ConfigurationError(
                f"destination.type '{self.type}' must be one of: "
                f"{VALID_DESTINATION_TYPES}",
                config_key="destinations[].type",
            )


@dataclass
class Config:
    """Complete SP-Base-Relay v2.0 configuration.

    v2.0 breaking change: ``server`` replaced by ``destinations`` list.
    """

    input: InputConfig
    destinations: list[DestinationConfig]
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)

    def get_enabled_destinations(self) -> list[DestinationConfig]:
        """Return only enabled destinations."""
        return [d for d in self.destinations if d.enabled]

    def get_destination_by_name(self, name: str) -> DestinationConfig | None:
        """Find a destination by name."""
        for d in self.destinations:
            if d.name == name:
                return d
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
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

            # ---- Detect old v1.x format (DR-4) ----
            if "server" in data:
                raise ConfigurationError(
                    "Old v1.x configuration format detected: 'server:' is no longer "
                    "supported. Please migrate to v2.0 'destinations:' list format.\n"
                    "See config.example.yaml for the new format.\n"
                    "Migration: move server settings into a destination entry:\n"
                    "  destinations:\n"
                    "    - name: surepath\n"
                    "      type: surepath\n"
                    "      enabled: true\n"
                    "      filter:\n"
                    "        mode: pass_all\n"
                    "      config:\n"
                    "        host: <your_host>\n"
                    "        port: <your_port>\n"
                    "        username: <your_username>\n"
                    "        password: <your_password>",
                    config_key="server",
                )

            # ---- Parse input configuration ----
            input_data = data.get("input", {})

            if "type" in input_data or "tcp" in input_data or "serial" in input_data:
                raise ConfigurationError(
                    "Old input configuration format detected. "
                    "Please use 'source' and 'config' keys.\n"
                    "  input:\n"
                    "    source: tcp\n"
                    "    config:\n"
                    "      host: 127.0.0.1\n"
                    "      port: 5015",
                    config_key="input",
                )

            if "source" not in input_data:
                raise ConfigurationError(
                    "input.source is required (tcp, serial, usb_serial, bluetooth)",
                    config_key="input.source",
                )

            if "config" not in input_data:
                raise ConfigurationError(
                    "input.config is required (source-specific parameters)",
                    config_key="input.config",
                )

            input_config = InputConfig(
                source=input_data["source"], config=input_data["config"]
            )

            # ---- Parse destinations list (v2.0) ----
            if "destinations" not in data:
                raise ConfigurationError(
                    "destinations list is required (at least one destination)",
                    config_key="destinations",
                )

            raw_destinations = data["destinations"]
            if (
                not isinstance(raw_destinations, list)
                or len(cast(list[Any], raw_destinations)) == 0
            ):
                raise ConfigurationError(
                    "destinations must be a non-empty list",
                    config_key="destinations",
                )

            dest_list = cast(list[Any], raw_destinations)
            destinations: list[DestinationConfig] = []
            seen_names: set[str] = set()

            for i, raw_dest in enumerate(dest_list):
                if not isinstance(raw_dest, dict):
                    raise ConfigurationError(
                        f"destinations[{i}] must be a dictionary",
                        config_key=f"destinations[{i}]",
                    )

                dest = _parse_destination(cast(dict[str, Any], raw_dest), i)
                if dest.name in seen_names:
                    raise ConfigurationError(
                        f"Duplicate destination name: '{dest.name}'",
                        config_key=f"destinations[{i}].name",
                    )
                seen_names.add(dest.name)
                destinations.append(dest)

            # Validate at least one enabled destination
            enabled = [d for d in destinations if d.enabled]
            if not enabled:
                raise ConfigurationError(
                    "At least one destination must be enabled",
                    config_key="destinations",
                )

            # ---- Parse global settings ----
            metrics_data = data.get("metrics", {})
            metrics = MetricsConfig(**metrics_data)

            logging_data = data.get("logging", {})
            logging_config = LoggingConfig(**logging_data)

            service_data = data.get("service", {})
            service = ServiceConfig(**service_data)

            return cls(
                input=input_config,
                destinations=destinations,
                metrics=metrics,
                logging=logging_config,
                service=service,
            )

        except ConfigurationError:
            raise
        except Exception as e:
            raise ConfigurationError(f"Invalid configuration format: {e}")


def _parse_destination(raw: dict[str, Any], index: int) -> DestinationConfig:
    """Parse a single destination entry from the YAML destinations list.

    Args:
        raw: Raw dictionary from YAML.
        index: Index in the destinations list (for error messages).

    Returns:
        Validated DestinationConfig.

    Raises:
        ConfigurationError: If destination is invalid.
    """
    prefix = f"destinations[{index}]"

    # Required fields
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ConfigurationError(
            f"{prefix}.name is required and must be a string",
            config_key=f"{prefix}.name",
        )

    dest_type = raw.get("type")
    if not dest_type or not isinstance(dest_type, str):
        raise ConfigurationError(
            f"{prefix}.type is required and must be a string",
            config_key=f"{prefix}.type",
        )
    if dest_type not in VALID_DESTINATION_TYPES:
        raise ConfigurationError(
            f"{prefix}.type '{dest_type}' must be one of: {VALID_DESTINATION_TYPES}",
            config_key=f"{prefix}.type",
        )

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigurationError(
            f"{prefix}.enabled must be a boolean",
            config_key=f"{prefix}.enabled",
        )

    # Parse filter block
    raw_filter = raw.get("filter", {})
    if not isinstance(raw_filter, dict):
        raise ConfigurationError(
            f"{prefix}.filter must be a dictionary",
            config_key=f"{prefix}.filter",
        )
    filter_data = cast(dict[str, Any], raw_filter)
    filter_config = DestinationFilterConfig(
        mode=str(filter_data.get("mode", "pass_all")),
        message_ids=list(filter_data.get("message_ids", [])),
    )

    # Parse type-specific config block
    raw_config = raw.get("config", {})
    if not isinstance(raw_config, dict):
        raise ConfigurationError(
            f"{prefix}.config must be a dictionary",
            config_key=f"{prefix}.config",
        )
    config_data = cast(dict[str, Any], raw_config)

    typed_config: DestinationSpecificConfig
    try:
        if dest_type == "surepath":
            typed_config = SurePathDestinationConfig(**config_data)
        elif dest_type == "ntrip":
            typed_config = NtripDestinationConfig(**config_data)
        elif dest_type == "tcp_server":
            typed_config = TcpServerDestinationConfig(**config_data)
        else:
            raise ConfigurationError(
                f"{prefix}.type '{dest_type}' is not supported",
                config_key=f"{prefix}.type",
            )
    except ConfigurationError:
        raise
    except TypeError as e:
        raise ConfigurationError(
            f"{prefix}.config has invalid fields: {e}",
            config_key=f"{prefix}.config",
        )

    return DestinationConfig(
        name=name,
        type=dest_type,
        enabled=enabled,
        filter=filter_config,
        config=typed_config,
    )


class ConfigManager:
    """Configuration manager for SP-Base-Relay."""

    DEFAULT_CONFIG_LOCATIONS = [
        "/etc/sp-rtk-base-relay/config.yaml",
        "~/.config/sp-rtk-base-relay/config.yaml",
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
            with open(config_file) as f:
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

    # Fields that should be converted to int from env vars
    _INT_FIELDS = {
        "port",
        "baudrate",
        "bytesize",
        "heartbeat_timeout",
        "reconnect_max_delay",
        "connection_timeout",
        "read_timeout",
        "retry_initial_delay",
        "retry_max_delay",
        "max_clients",
    }
    # Fields that should be converted to float from env vars
    _FLOAT_FIELDS = {"retry_multiplier", "timeout", "stopbits"}
    # Fields that should be converted to bool from env vars
    _BOOL_FIELDS = {"enabled", "rtscts", "xonxoff"}

    @classmethod
    def _apply_env_overrides(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Apply environment variable overrides to configuration data.

        v2.0 supports two categories of env overrides:
        - Global: SP_INPUT_*, SP_METRICS_*, SP_LOG_*
        - Per-destination: SP_DEST_<NAME>_<FIELD> (dynamic, based on names in config)

        Args:
            data: Configuration data dictionary

        Returns:
            Configuration data with environment overrides applied
        """
        # --- Global env mappings (input, metrics, logging) ---
        global_mappings: dict[str, tuple[str, ...]] = {
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
            f"{cls.ENV_PREFIX}METRICS_ENABLED": ("metrics", "enabled"),
            f"{cls.ENV_PREFIX}METRICS_PORT": ("metrics", "port"),
            f"{cls.ENV_PREFIX}LOG_LEVEL": ("logging", "level"),
            f"{cls.ENV_PREFIX}LOG_FORMAT": ("logging", "format"),
        }

        for env_var, config_path in global_mappings.items():
            env_value = os.getenv(env_var)
            if env_value is not None:
                cls._set_nested(data, config_path, env_value)

        # --- Dynamic per-destination env overrides: SP_DEST_<NAME>_<FIELD> ---
        raw_destinations = data.get("destinations")
        if isinstance(raw_destinations, list):
            for dest_data in cast(list[Any], raw_destinations):
                if not isinstance(dest_data, dict):
                    continue
                dest_dict = cast(dict[str, Any], dest_data)
                name = dest_dict.get("name")
                if not isinstance(name, str):
                    continue
                env_prefix = f"{cls.ENV_PREFIX}DEST_{name.upper()}_"
                for env_key, env_value in os.environ.items():
                    if env_key.startswith(env_prefix):
                        field_name = env_key[len(env_prefix) :].lower()
                        if "config" not in dest_dict:
                            dest_dict["config"] = {}
                        config_dict = cast(dict[str, Any], dest_dict["config"])
                        config_dict[field_name] = cls._convert_env_value(
                            field_name, env_value
                        )

        return data

    @classmethod
    def _set_nested(
        cls, data: dict[str, Any], path: tuple[str, ...], value: str
    ) -> None:
        """Set a value in a nested dict, creating intermediate dicts as needed."""
        current: dict[str, Any] = data
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        final_key = path[-1]
        current[final_key] = cls._convert_env_value(final_key, value)

    @classmethod
    def _convert_env_value(
        cls, field_name: str, value: str
    ) -> str | int | float | bool:
        """Convert a string env value to the appropriate Python type."""
        if field_name in cls._INT_FIELDS:
            try:
                return int(value)
            except ValueError:
                return value
        elif field_name in cls._FLOAT_FIELDS:
            try:
                return float(value)
            except ValueError:
                return value
        elif field_name in cls._BOOL_FIELDS:
            return value.lower() in ("true", "1", "yes", "on")
        return value

    @classmethod
    def generate_default_config(cls) -> str:
        """Generate default configuration file content.

        Returns:
            Default configuration as YAML string
        """
        default_config: dict[str, Any] = {
            "input": {
                "source": "tcp",
                "config": {
                    "host": "127.0.0.1",
                    "port": 5015,
                    "timeout": 5.0,
                    "buffer_size": 4096,
                },
            },
            "destinations": [
                {
                    "name": "surepath",
                    "type": "surepath",
                    "enabled": True,
                    "filter": {"mode": "pass_all"},
                    "config": {
                        "host": "rtcm.example.com",
                        "port": 50010,
                        "username": "your_username",
                        "password": "your_password",
                        "connection_timeout": 10,
                        "heartbeat_timeout": 30,
                        "retry_initial_delay": 15,
                        "retry_max_delay": 60,
                        "retry_multiplier": 2.0,
                    },
                },
                {
                    "name": "rtk2go",
                    "type": "ntrip",
                    "enabled": False,
                    "filter": {"mode": "pass_all"},
                    "config": {
                        "caster": "rtk2go.com",
                        "port": 2101,
                        "mountpoint": "YOUR_MOUNT",
                        "password": "your_password",
                        "version": "2.0",
                    },
                },
            ],
            "metrics": {
                "enabled": True,
                "host": "0.0.0.0",
                "port": 8080,
                "path": "/metrics",
            },
            "logging": {
                "level": "INFO",
                "format": "json",
                "file": "/var/log/sp-rtk-base-relay.log",
                "max_size_mb": 50,
                "backup_count": 3,
            },
            "service": {
                "daemon": False,
                "pid_file": "/var/run/sp-rtk-base-relay.pid",
                "user": "sp-rtk-base-relay",
                "group": "sp-rtk-base-relay",
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
