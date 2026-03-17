"""Unit tests for SP-Base-Relay exceptions."""

import pytest

from sp_base_relay.exceptions import (
    SPBaseRelayError,
    ConfigurationError,
    ConnectionError,
    AuthenticationError,
    InputSourceError,
    DataProcessingError,
    ServiceError,
    DestinationError,
    NtripError,
)


class TestSPBaseRelayError:
    """Test base exception class."""

    def test_basic_exception(self):
        """Test basic exception creation."""
        error = SPBaseRelayError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.details is None

    def test_exception_with_details(self):
        """Test exception with details."""
        error = SPBaseRelayError("Test error", "Additional details")
        assert str(error) == "Test error: Additional details"
        assert error.message == "Test error"
        assert error.details == "Additional details"

    def test_inheritance(self):
        """Test that it properly inherits from Exception."""
        error = SPBaseRelayError("Test error")
        assert isinstance(error, Exception)


class TestConfigurationError:
    """Test configuration exception class."""

    def test_basic_config_error(self):
        """Test basic configuration error."""
        error = ConfigurationError("Invalid config")
        assert "Invalid config" in str(error)
        assert error.config_path is None
        assert error.config_key is None

    def test_config_error_with_key(self):
        """Test configuration error with key."""
        error = ConfigurationError("Invalid value", config_key="server.port")
        assert "Invalid value" in str(error)
        assert "Key: server.port" in str(error)
        assert error.config_key == "server.port"

    def test_config_error_with_path(self):
        """Test configuration error with file path."""
        error = ConfigurationError("File not found", config_path="/etc/config.yaml")
        assert "File not found" in str(error)
        assert "File: /etc/config.yaml" in str(error)
        assert error.config_path == "/etc/config.yaml"

    def test_config_error_with_all_fields(self):
        """Test configuration error with all fields."""
        error = ConfigurationError(
            "Invalid value",
            config_path="/etc/config.yaml",
            config_key="server.port",
            details="Port must be 1-65535",
        )
        assert "Invalid value" in str(error)
        assert "Key: server.port" in str(error)
        assert "File: /etc/config.yaml" in str(error)
        assert error.details == "Port must be 1-65535"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = ConfigurationError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestConnectionError:
    """Test connection exception class."""

    def test_basic_connection_error(self):
        """Test basic connection error."""
        error = ConnectionError("Connection failed")
        assert "Connection failed" in str(error)
        assert error.host is None
        assert error.port is None

    def test_connection_error_with_host(self):
        """Test connection error with host."""
        error = ConnectionError("Connection failed", host="example.com")
        assert "Connection failed" in str(error)
        assert "Host: example.com" in str(error)
        assert error.host == "example.com"

    def test_connection_error_with_host_and_port(self):
        """Test connection error with host and port."""
        error = ConnectionError("Connection failed", host="example.com", port=8080)
        assert "Connection failed" in str(error)
        assert "Target: example.com:8080" in str(error)
        assert error.host == "example.com"
        assert error.port == 8080

    def test_connection_error_with_details(self):
        """Test connection error with details."""
        error = ConnectionError(
            "Connection failed",
            host="example.com",
            port=8080,
            details="Connection refused",
        )
        assert "Connection failed" in str(error)
        assert "Target: example.com:8080" in str(error)
        assert error.details == "Connection refused"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = ConnectionError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestAuthenticationError:
    """Test authentication exception class."""

    def test_basic_auth_error(self):
        """Test basic authentication error."""
        error = AuthenticationError("Authentication failed")
        assert "Authentication failed" in str(error)
        assert error.username is None

    def test_auth_error_with_username(self):
        """Test authentication error with username."""
        error = AuthenticationError("Authentication failed", username="testuser")
        assert "Authentication failed" in str(error)
        assert "Username: testuser" in str(error)
        assert error.username == "testuser"

    def test_auth_error_with_details(self):
        """Test authentication error with details."""
        error = AuthenticationError(
            "Authentication failed", username="testuser", details="Invalid password"
        )
        assert "Authentication failed" in str(error)
        assert "Username: testuser" in str(error)
        assert error.details == "Invalid password"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = AuthenticationError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestInputSourceError:
    """Test input source exception class."""

    def test_basic_input_error(self):
        """Test basic input source error."""
        error = InputSourceError("Input failed")
        assert "Input failed" in str(error)
        assert error.source_type is None
        assert error.source_path is None

    def test_input_error_with_type(self):
        """Test input source error with type."""
        error = InputSourceError("Input failed", source_type="serial")
        assert "Input failed" in str(error)
        assert "Type: serial" in str(error)
        assert error.source_type == "serial"

    def test_input_error_with_path(self):
        """Test input source error with path."""
        error = InputSourceError("Input failed", source_path="/dev/ttyUSB0")
        assert "Input failed" in str(error)
        assert "Path: /dev/ttyUSB0" in str(error)
        assert error.source_path == "/dev/ttyUSB0"

    def test_input_error_with_all_fields(self):
        """Test input source error with all fields."""
        error = InputSourceError(
            "Input failed",
            source_type="serial",
            source_path="/dev/ttyUSB0",
            details="Permission denied",
        )
        assert "Input failed" in str(error)
        assert "Type: serial" in str(error)
        assert "Path: /dev/ttyUSB0" in str(error)
        assert error.details == "Permission denied"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = InputSourceError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestDataProcessingError:
    """Test data processing exception class."""

    def test_basic_data_error(self):
        """Test basic data processing error."""
        error = DataProcessingError("Processing failed")
        assert "Processing failed" in str(error)
        assert error.data_size is None

    def test_data_error_with_size(self):
        """Test data processing error with size."""
        error = DataProcessingError("Processing failed", data_size=1024)
        assert "Processing failed" in str(error)
        assert "Data size: 1024 bytes" in str(error)
        assert error.data_size == 1024

    def test_data_error_with_zero_size(self):
        """Test data processing error with zero size."""
        error = DataProcessingError("Processing failed", data_size=0)
        assert "Processing failed" in str(error)
        assert "Data size: 0 bytes" in str(error)
        assert error.data_size == 0

    def test_data_error_with_details(self):
        """Test data processing error with details."""
        error = DataProcessingError(
            "Processing failed", data_size=1024, details="Buffer overflow"
        )
        assert "Processing failed" in str(error)
        assert "Data size: 1024 bytes" in str(error)
        assert error.details == "Buffer overflow"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = DataProcessingError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestServiceError:
    """Test service exception class."""

    def test_basic_service_error(self):
        """Test basic service error."""
        error = ServiceError("Service failed")
        assert "Service failed" in str(error)
        assert error.service_name is None

    def test_service_error_with_name(self):
        """Test service error with service name."""
        error = ServiceError("Service failed", service_name="sp-base-relay")
        assert "Service failed" in str(error)
        assert "Service: sp-base-relay" in str(error)
        assert error.service_name == "sp-base-relay"

    def test_service_error_with_details(self):
        """Test service error with details."""
        error = ServiceError(
            "Service failed",
            service_name="sp-base-relay",
            details="Failed to bind to port",
        )
        assert "Service failed" in str(error)
        assert "Service: sp-base-relay" in str(error)
        assert error.details == "Failed to bind to port"

    def test_inheritance(self):
        """Test inheritance from SPBaseRelayError."""
        error = ServiceError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestDestinationError:
    """Test destination exception class."""

    def test_basic_destination_error(self) -> None:
        """Test basic destination error."""
        error = DestinationError("Destination failed")
        assert "Destination failed" in str(error)
        assert error.destination_name is None
        assert error.destination_type is None

    def test_destination_error_with_name(self) -> None:
        """Test destination error with name."""
        error = DestinationError("Send failed", destination_name="rtk2go")
        assert "Send failed" in str(error)
        assert "Destination: rtk2go" in str(error)
        assert error.destination_name == "rtk2go"

    def test_destination_error_with_type(self) -> None:
        """Test destination error with type."""
        error = DestinationError("Send failed", destination_type="ntrip")
        assert "Send failed" in str(error)
        assert "Type: ntrip" in str(error)
        assert error.destination_type == "ntrip"

    def test_destination_error_with_all_fields(self) -> None:
        """Test destination error with all fields."""
        error = DestinationError(
            "Send failed",
            destination_name="rtk2go",
            destination_type="ntrip",
            details="Connection refused",
        )
        assert "Send failed" in str(error)
        assert "Destination: rtk2go" in str(error)
        assert "Type: ntrip" in str(error)
        assert error.details == "Connection refused"

    def test_inheritance(self) -> None:
        """Test inheritance from SPBaseRelayError."""
        error = DestinationError("Test error")
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)


class TestNtripError:
    """Test NTRIP-specific exception class."""

    def test_basic_ntrip_error(self) -> None:
        """Test basic NTRIP error."""
        error = NtripError("NTRIP auth failed")
        assert "NTRIP auth failed" in str(error)
        assert error.caster is None
        assert error.mountpoint is None
        assert error.destination_type == "ntrip"

    def test_ntrip_error_with_caster(self) -> None:
        """Test NTRIP error with caster."""
        error = NtripError("Auth failed", caster="rtk2go.com")
        assert "Auth failed" in str(error)
        assert "Caster: rtk2go.com" in str(error)
        assert error.caster == "rtk2go.com"

    def test_ntrip_error_with_mountpoint(self) -> None:
        """Test NTRIP error with mountpoint."""
        error = NtripError("Mountpoint rejected", mountpoint="RODEN01")
        assert "Mountpoint rejected" in str(error)
        assert "Mountpoint: RODEN01" in str(error)
        assert error.mountpoint == "RODEN01"

    def test_ntrip_error_with_all_fields(self) -> None:
        """Test NTRIP error with all fields."""
        error = NtripError(
            "Auth failed",
            caster="rtk2go.com",
            mountpoint="RODEN01",
            destination_name="rtk2go",
            details="Invalid password",
        )
        assert "Auth failed" in str(error)
        assert "Caster: rtk2go.com" in str(error)
        assert "Mountpoint: RODEN01" in str(error)
        assert "Destination: rtk2go" in str(error)
        assert error.details == "Invalid password"
        assert error.destination_name == "rtk2go"
        assert error.destination_type == "ntrip"

    def test_inheritance_from_destination_error(self) -> None:
        """Test inheritance from DestinationError."""
        error = NtripError("Test error")
        assert isinstance(error, DestinationError)
        assert isinstance(error, SPBaseRelayError)
        assert isinstance(error, Exception)

    def test_destination_type_always_ntrip(self) -> None:
        """destination_type is always 'ntrip'."""
        error = NtripError("Test error")
        assert error.destination_type == "ntrip"


class TestExceptionChaining:
    """Test exception chaining and context."""

    def test_exception_chaining(self):
        """Test that exceptions can be chained properly."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise ConfigurationError("Config error") from e
        except ConfigurationError as config_error:
            assert config_error.__cause__ is not None
            assert isinstance(config_error.__cause__, ValueError)
            assert str(config_error.__cause__) == "Original error"

    def test_exception_context(self):
        """Test exception context preservation."""
        try:
            try:
                raise ConnectionError("Connection failed")
            except ConnectionError:
                raise AuthenticationError("Auth failed")
        except AuthenticationError as auth_error:
            assert auth_error.__context__ is not None
            assert isinstance(auth_error.__context__, ConnectionError)


if __name__ == "__main__":
    pytest.main([__file__])
