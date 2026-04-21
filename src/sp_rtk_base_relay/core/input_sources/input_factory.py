"""Input source factory for dynamic source creation.

This module provides the InputSourceFactory for creating appropriate input
source instances based on configuration parameters. Supports multiple input
types with proper validation and error handling.
"""

import logging
from typing import Any
from collections.abc import Callable

from .base_input import InputSource
from .serial_input import SerialInputSource, SerialConfig
from ...exceptions import InputSourceError, ConfigurationError


logger = logging.getLogger(__name__)


class InputSourceFactory:
    """Factory for creating input source instances.

    Provides centralized creation of input source objects based on
    configuration parameters. Supports registration of new input
    source types and validation of configuration parameters.
    """

    # Registry of available input source types
    _source_types: dict[str, type[InputSource]] = {
        "serial": SerialInputSource,
    }

    # Configuration builders for each source type
    _config_builders: dict[str, Callable[[dict[str, Any]], Any]] = {
        "serial": lambda cfg: SerialConfig(**cfg),
    }

    @classmethod
    def register_source_type(
        cls,
        source_type: str,
        source_class: type[InputSource],
        config_builder: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Register a new input source type.

        Args:
            source_type: String identifier for the source type
            source_class: InputSource class to instantiate
            config_builder: Function to build config object from dict
        """
        cls._source_types[source_type] = source_class
        cls._config_builders[source_type] = config_builder
        logger.info(f"Registered input source type: {source_type}")

    @classmethod
    def get_available_types(cls) -> list[str]:
        """Get list of available input source types.

        Returns:
            List of available source type names
        """
        return list(cls._source_types.keys())

    @classmethod
    def create_input_source(
        cls, source_type: str, config: dict[str, Any]
    ) -> InputSource:
        """Create an input source instance.

        Args:
            source_type: Type of input source to create
            config: Configuration parameters for the source

        Returns:
            Configured InputSource instance

        Raises:
            ConfigurationError: If source type is unknown or config is invalid
            InputSourceError: If source creation fails
        """
        logger.info(f"Creating {source_type} input source")

        # Validate source type
        if source_type not in cls._source_types:
            available = ", ".join(cls.get_available_types())
            raise ConfigurationError(
                f"Unknown input source type '{source_type}'. "
                f"Available types: {available}"
            )

        try:
            # Get source class and config builder
            source_class = cls._source_types[source_type]
            config_builder = cls._config_builders[source_type]

            # Build configuration object
            source_config = config_builder(config)

            # Create and return source instance
            source = source_class(source_config)

            logger.info(
                f"Created {source_type} input source: {source.get_connection_info()}"
            )

            return source

        except Exception as e:
            error_msg = f"Failed to create {source_type} input source: {e}"
            logger.error(error_msg)
            raise InputSourceError(error_msg) from e

    @classmethod
    def validate_config(cls, source_type: str, config: dict[str, Any]) -> bool:
        """Validate configuration for a source type.

        Args:
            source_type: Type of input source
            config: Configuration parameters

        Returns:
            True if configuration is valid

        Raises:
            ConfigurationError: If validation fails
        """
        if source_type not in cls._source_types:
            available = ", ".join(cls.get_available_types())
            raise ConfigurationError(
                f"Unknown input source type '{source_type}'. "
                f"Available types: {available}"
            )

        try:
            # Try to build configuration object
            config_builder = cls._config_builders[source_type]
            config_builder(config)
            return True

        except Exception as e:
            raise ConfigurationError(
                f"Invalid configuration for {source_type} input source: {e}"
            ) from e

    @classmethod
    def get_config_schema(cls, source_type: str) -> dict[str, Any]:
        """Get configuration schema for a source type.

        Args:
            source_type: Type of input source

        Returns:
            Dictionary describing expected configuration parameters

        Raises:
            ConfigurationError: If source type is unknown
        """
        if source_type not in cls._source_types:
            available = ", ".join(cls.get_available_types())
            raise ConfigurationError(
                f"Unknown input source type '{source_type}'. "
                f"Available types: {available}"
            )

        # Return schema based on source type
        if source_type == "serial":
            return {
                "port": {
                    "type": "string",
                    "description": "Serial port device path",
                    "default": "/dev/ttyUSB0",
                    "examples": ["/dev/ttyUSB0", "/dev/ttyS0", "/dev/ttyACM0"],
                },
                "baud_rate": {
                    "type": "integer",
                    "description": "Serial port baud rate",
                    "default": 115200,
                    "examples": [9600, 19200, 38400, 57600, 115200, 230400],
                },
                "data_bits": {
                    "type": "integer",
                    "description": "Number of data bits",
                    "default": 8,
                    "choices": [5, 6, 7, 8],
                },
                "stop_bits": {
                    "type": "number",
                    "description": "Number of stop bits",
                    "default": 1,
                    "choices": [1, 1.5, 2],
                },
                "parity": {
                    "type": "string",
                    "description": "Parity checking",
                    "default": "none",
                    "choices": ["none", "even", "odd", "mark", "space"],
                },
                "timeout": {
                    "type": "number",
                    "description": "Connection timeout in seconds",
                    "default": 5.0,
                    "minimum": 0.1,
                },
                "read_timeout": {
                    "type": "number",
                    "description": "Read timeout in seconds",
                    "default": 1.0,
                    "minimum": 0.1,
                },
            }
        elif source_type == "tcp":
            return {
                "host": {
                    "type": "string",
                    "description": "TCP host to connect to",
                    "default": "localhost",
                    "examples": ["localhost", "127.0.0.1", "rtkbase.local"],
                },
                "port": {
                    "type": "integer",
                    "description": "TCP port number",
                    "default": 5015,
                    "examples": [5015, 2101, 8080],
                },
                "timeout": {
                    "type": "number",
                    "description": "Connection timeout in seconds",
                    "default": 10.0,
                    "minimum": 0.1,
                },
                "read_timeout": {
                    "type": "number",
                    "description": "Read timeout in seconds",
                    "default": 1.0,
                    "minimum": 0.1,
                },
                "buffer_size": {
                    "type": "integer",
                    "description": "TCP receive buffer size",
                    "default": 8192,
                    "minimum": 1024,
                },
                "keepalive": {
                    "type": "boolean",
                    "description": "Enable TCP keepalive",
                    "default": True,
                },
            }
        elif source_type == "bluetooth":
            return {
                "device_name": {
                    "type": "string",
                    "description": "Bluetooth device name for auto-discovery",
                    "default": None,
                    "examples": ["RTK_GPS_BASE", "GPS Receiver", "GNSS"],
                },
                "mac_address": {
                    "type": "string",
                    "description": "Bluetooth MAC address (if known)",
                    "default": None,
                    "examples": ["00:11:22:33:44:55", "00:11:22:33:44:55"],
                },
                "auto_pair": {
                    "type": "boolean",
                    "description": "Automatically pair if not paired",
                    "default": True,
                },
                "auto_trust": {
                    "type": "boolean",
                    "description": "Automatically trust device",
                    "default": True,
                },
                "pin": {
                    "type": "string",
                    "description": "PIN code for pairing",
                    "default": "0000",
                },
                "adapter_name": {
                    "type": "string",
                    "description": "Bluetooth adapter to use",
                    "default": "hci0",
                    "examples": ["hci0", "hci1"],
                },
                "scan_timeout": {
                    "type": "integer",
                    "description": "Device discovery timeout (seconds)",
                    "default": 10,
                    "minimum": 1,
                },
                "read_timeout": {
                    "type": "number",
                    "description": "Socket read timeout (seconds)",
                    "default": 1.0,
                    "minimum": 0.1,
                },
                "connect_timeout": {
                    "type": "number",
                    "description": "Connection timeout (seconds)",
                    "default": 10.0,
                    "minimum": 0.1,
                },
            }

        # For future source types, add their schemas here
        return {}

    @classmethod
    def create_example_config(cls, source_type: str) -> dict[str, Any]:
        """Create an example configuration for a source type.

        Args:
            source_type: Type of input source

        Returns:
            Dictionary with example configuration

        Raises:
            ConfigurationError: If source type is unknown
        """
        schema = cls.get_config_schema(source_type)

        example_config: dict[str, Any] = {}
        for param_name, param_info in schema.items():
            if "default" in param_info:
                example_config[param_name] = param_info["default"]
            elif "examples" in param_info and param_info["examples"]:
                example_config[param_name] = param_info["examples"][0]
            elif "choices" in param_info and param_info["choices"]:
                example_config[param_name] = param_info["choices"][0]

        return example_config

    @classmethod
    def get_source_info(cls, source_type: str) -> dict[str, Any]:
        """Get detailed information about a source type.

        Args:
            source_type: Type of input source

        Returns:
            Dictionary with source type information

        Raises:
            ConfigurationError: If source type is unknown
        """
        if source_type not in cls._source_types:
            available = ", ".join(cls.get_available_types())
            raise ConfigurationError(
                f"Unknown input source type '{source_type}'. "
                f"Available types: {available}"
            )

        source_class = cls._source_types[source_type]

        info: dict[str, Any] = {
            "type": source_type,
            "class": source_class.__name__,
            "module": source_class.__module__,
            "description": source_class.__doc__.strip() if source_class.__doc__ else "",
            "config_schema": cls.get_config_schema(source_type),
            "example_config": cls.create_example_config(source_type),
        }

        # Add source-specific information
        if source_type == "serial":
            serial_info = {
                "supports": [
                    "Direct GNSS receiver connections",
                    "USB-to-serial adapters",
                    "UART connections",
                ],
                "requirements": [
                    "PySerial library installed",
                    "Serial port device accessible",
                    "Appropriate permissions for serial port access",
                ],
            }
            info.update(serial_info)

        return info


# Register TCP input source when it's implemented
def _register_tcp_source() -> None:
    """Register TCP input source if available."""
    try:
        from .tcp_input import TCPInputSource, TCPConfig

        InputSourceFactory.register_source_type(
            "tcp", TCPInputSource, lambda cfg: TCPConfig(**cfg)
        )

        logger.debug("TCP input source registered")
    except ImportError:
        # TCP source not yet implemented
        logger.debug("TCP input source not available")


# Register Bluetooth input source
def _register_bluetooth_source() -> None:
    """Register Bluetooth input source if available."""
    try:
        from .bluetooth_input import BluetoothInputSource, BluetoothConfig

        InputSourceFactory.register_source_type(
            "bluetooth", BluetoothInputSource, lambda cfg: BluetoothConfig(**cfg)
        )

        logger.debug("Bluetooth input source registered")
    except ImportError:
        # Bluetooth source not available (missing pydbus or bluetooth_manager)
        logger.debug("Bluetooth input source not available")


# Try to register additional source types
_register_tcp_source()
_register_bluetooth_source()
