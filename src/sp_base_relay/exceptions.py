"""Custom exceptions for SP-Base-Relay.

This module defines all custom exceptions used throughout the SP-Base-Relay
application, providing clear error handling and debugging information.
"""


class SPBaseRelayError(Exception):
    """Base exception class for all SP-Base-Relay related errors.

    All custom exceptions in the SP-Base-Relay package should inherit from
    this base class to provide consistent error handling.
    """

    def __init__(self, message: str, details: str | None = None) -> None:
        """Initialize the base exception.

        Args:
            message: The error message describing what went wrong
            details: Optional additional details about the error
        """
        self.message = message
        self.details = details

        full_message = message
        if details:
            full_message = f"{message}: {details}"

        super().__init__(full_message)


class ConfigurationError(SPBaseRelayError):
    """Exception raised for configuration-related errors.

    This includes issues with:
    - Invalid configuration file syntax
    - Missing required configuration values
    - Invalid configuration value types or ranges
    - Configuration validation failures
    """

    def __init__(
        self,
        message: str,
        config_path: str | None = None,
        config_key: str | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize configuration error.

        Args:
            message: The error message
            config_path: Optional path to the configuration file
            config_key: Optional configuration key that caused the error
            details: Optional additional error details
        """
        self.config_path = config_path
        self.config_key = config_key

        # Build detailed error message
        error_parts = [message]

        if config_key:
            error_parts.append(f"Key: {config_key}")
        if config_path:
            error_parts.append(f"File: {config_path}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class ConnectionError(SPBaseRelayError):
    """Exception raised for connection-related errors.

    This includes issues with:
    - Failed TCP connections to RTCM server
    - Network timeouts
    - Socket errors
    - DNS resolution failures
    """

    def __init__(
        self,
        message: str,
        host: str | None = None,
        port: int | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize connection error.

        Args:
            message: The error message
            host: Optional hostname or IP that failed to connect
            port: Optional port number that failed to connect
            details: Optional additional error details
        """
        self.host = host
        self.port = port

        # Build detailed error message
        error_parts = [message]

        if host and port:
            error_parts.append(f"Target: {host}:{port}")
        elif host:
            error_parts.append(f"Host: {host}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class AuthenticationError(SPBaseRelayError):
    """Exception raised for authentication-related errors.

    This includes issues with:
    - Failed RTCM server authentication
    - Invalid credentials
    - Authentication timeouts
    - Unexpected authentication responses
    """

    def __init__(
        self, message: str, username: str | None = None, details: str | None = None
    ) -> None:
        """Initialize authentication error.

        Args:
            message: The error message
            username: Optional username that failed authentication
            details: Optional additional error details
        """
        self.username = username

        # Build detailed error message
        error_parts = [message]

        if username:
            error_parts.append(f"Username: {username}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class InputSourceError(SPBaseRelayError):
    """Exception raised for input source-related errors.

    This includes issues with:
    - Failed serial port connections
    - TCP input source connection failures
    - Device not found errors
    - Permission errors accessing devices
    """

    def __init__(
        self,
        message: str,
        source_type: str | None = None,
        source_path: str | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize input source error.

        Args:
            message: The error message
            source_type: Optional type of input source (tcp, serial, etc.)
            source_path: Optional path/address of the source
            details: Optional additional error details
        """
        self.source_type = source_type
        self.source_path = source_path

        # Build detailed error message
        error_parts = [message]

        if source_type:
            error_parts.append(f"Type: {source_type}")
        if source_path:
            error_parts.append(f"Path: {source_path}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class DataProcessingError(SPBaseRelayError):
    """Exception raised for data processing-related errors.

    This includes issues with:
    - Data corruption during processing
    - Buffer overflow conditions
    - Threading synchronization errors
    - Data validation failures
    """

    def __init__(
        self, message: str, data_size: int | None = None, details: str | None = None
    ) -> None:
        """Initialize data processing error.

        Args:
            message: The error message
            data_size: Optional size of data that caused the error
            details: Optional additional error details
        """
        self.data_size = data_size

        # Build detailed error message
        error_parts = [message]

        if data_size is not None:
            error_parts.append(f"Data size: {data_size} bytes")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class ServiceError(SPBaseRelayError):
    """Exception raised for service management-related errors.

    This includes issues with:
    - Service startup failures
    - Service shutdown errors
    - Resource allocation failures
    - System service integration issues
    """

    def __init__(
        self, message: str, service_name: str | None = None, details: str | None = None
    ) -> None:
        """Initialize service error.

        Args:
            message: The error message
            service_name: Optional name of the service that failed
            details: Optional additional error details
        """
        self.service_name = service_name

        # Build detailed error message
        error_parts = [message]

        if service_name:
            error_parts.append(f"Service: {service_name}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class DestinationError(SPBaseRelayError):
    """Exception raised for destination-related errors.

    This includes issues with:
    - Destination connection failures
    - Send failures to destination servers
    - Destination configuration errors
    - Queue overflow or processing errors
    """

    def __init__(
        self,
        message: str,
        destination_name: str | None = None,
        destination_type: str | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize destination error.

        Args:
            message: The error message
            destination_name: Optional name of the destination that failed
            destination_type: Optional type of destination (surepath, ntrip, tcp_server)
            details: Optional additional error details
        """
        self.destination_name = destination_name
        self.destination_type = destination_type

        # Build detailed error message
        error_parts = [message]

        if destination_name:
            error_parts.append(f"Destination: {destination_name}")
        if destination_type:
            error_parts.append(f"Type: {destination_type}")

        full_message = " | ".join(error_parts)

        super().__init__(full_message, details)


class NtripError(DestinationError):
    """Exception raised for NTRIP-specific errors.

    This includes issues with:
    - NTRIP caster authentication failures
    - NTRIP protocol errors (v1.0 or v2.0)
    - Mountpoint not found or rejected
    - Caster connection refused
    """

    def __init__(
        self,
        message: str,
        caster: str | None = None,
        mountpoint: str | None = None,
        destination_name: str | None = None,
        details: str | None = None,
    ) -> None:
        """Initialize NTRIP error.

        Args:
            message: The error message
            caster: Optional caster hostname that failed
            mountpoint: Optional mountpoint name that caused the error
            destination_name: Optional name of the destination
            details: Optional additional error details
        """
        self.caster = caster
        self.mountpoint = mountpoint

        # Build detailed error message
        error_parts = [message]

        if caster:
            error_parts.append(f"Caster: {caster}")
        if mountpoint:
            error_parts.append(f"Mountpoint: {mountpoint}")
        if destination_name:
            error_parts.append(f"Destination: {destination_name}")

        full_message = " | ".join(error_parts)

        # Call SPBaseRelayError.__init__ directly to avoid double-formatting
        SPBaseRelayError.__init__(self, full_message, details)
        self.destination_name = destination_name
        self.destination_type = "ntrip"
