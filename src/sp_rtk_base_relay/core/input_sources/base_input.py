"""Abstract base class for input sources.

This module defines the InputSource ABC that all input source implementations
must inherit from, providing a consistent interface for reading RTCM data
from various input types.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class InputSourceStats:
    """Input source statistics and metrics."""

    connection_attempts: int = 0
    successful_connections: int = 0
    connection_failures: int = 0
    bytes_read: int = 0
    messages_read: int = 0
    read_errors: int = 0
    last_read_time: float = 0.0
    connected_since: float | None = None


class InputSource(ABC):
    """Abstract base class for all input sources.

    This class defines the interface that all input source implementations
    must provide for reading RTCM correction data from various sources
    such as serial ports, TCP connections, or USB serial adapters.
    """

    def __init__(self, source_type: str):
        """Initialize input source base.

        Args:
            source_type: Human-readable type name for logging
        """
        self.source_type = source_type
        self.stats = InputSourceStats()
        self._connected = False
        self._last_error: Exception | None = None

        logger.info(f"Initialized {source_type} input source")

    @property
    def is_connected(self) -> bool:
        """Check if input source is connected and ready to read data."""
        return self._connected

    @property
    def last_error(self) -> Exception | None:
        """Get the last error that occurred, if any."""
        return self._last_error

    @property
    def connection_statistics(self) -> InputSourceStats:
        """Get connection statistics."""
        return self.stats

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the input source.

        Establishes connection to the input source and prepares it for
        data reading. Must handle any necessary initialization.

        Returns:
            True if connection successful, False otherwise

        Raises:
            InputSourceError: If connection fails due to configuration or hardware issues
        """
        pass

    @abstractmethod
    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read RTCM data from the input source.

        Attempts to read available RTCM data from the connected source.
        This method should be non-blocking or use the specified timeout.

        Args:
            timeout: Maximum time to wait for data in seconds (None for default)

        Returns:
            Raw RTCM data bytes if available, None if no data or error

        Note:
            Returning None indicates either no data available or an error occurred.
            Check is_connected property to determine connection status.
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from input source and cleanup resources.

        Closes the connection and performs any necessary cleanup.
        Should be safe to call multiple times.
        """
        pass

    @abstractmethod
    def get_connection_info(self) -> dict[str, Any]:
        """Get connection information for logging and diagnostics.

        Returns:
            Dictionary containing connection details specific to the input type
        """
        pass

    def _update_connection_stats(self, connected: bool) -> None:
        """Update connection statistics.

        Args:
            connected: Whether connection was successful
        """
        self.stats.connection_attempts += 1

        if connected:
            self.stats.successful_connections += 1
            self.stats.connected_since = time.time()
            self._connected = True
            self._last_error = None
            logger.info(f"{self.source_type} input source connected successfully")
        else:
            self.stats.connection_failures += 1
            self._connected = False
            logger.error(f"{self.source_type} input source connection failed")

    def _update_read_stats(
        self, data: bytes | None, error: Exception | None = None
    ) -> None:
        """Update read statistics.

        Args:
            data: Data that was read, if any
            error: Error that occurred during read, if any
        """
        if error:
            self.stats.read_errors += 1
            self._last_error = error
            logger.debug(f"{self.source_type} read error: {error}")
        elif data:
            self.stats.bytes_read += len(data)
            self.stats.messages_read += 1
            self.stats.last_read_time = time.time()
            logger.debug(f"{self.source_type} read {len(data)} bytes")

        # If we got no data and no error, it's just no data available (normal)

    def _set_error_state(self, error: Exception) -> None:
        """Set input source to error state.

        Args:
            error: The error that caused the failure
        """
        self._connected = False
        self._last_error = error
        self.stats.connected_since = None
        logger.error(f"{self.source_type} input source error: {error}")

    def __str__(self) -> str:
        """String representation of input source."""
        connection_info = self.get_connection_info()
        info_str = ", ".join(f"{k}={v}" for k, v in connection_info.items())
        status = "connected" if self._connected else "disconnected"
        return f"{self.source_type}({info_str}) [{status}]"

    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"{self.__class__.__name__}("
            f"type='{self.source_type}', "
            f"connected={self._connected}, "
            f"stats={self.stats})"
        )
