"""Serial input source for GNSS receivers.

This module provides a serial port input source implementation for reading
RTCM correction data directly from GNSS receivers via serial connections
such as USB-to-serial adapters or direct UART connections.
"""

import logging
from dataclasses import dataclass
from typing import Any

from ...exceptions import InputSourceError
from .base_input import InputSource

try:
    import serial
    import serial.tools.list_ports

    _pyserial_available = True
except ImportError:
    _pyserial_available = False
    serial = None

logger = logging.getLogger(__name__)


@dataclass
class SerialConfig:
    """Serial port configuration parameters."""

    port: str = "/dev/ttyUSB0"
    baudrate: int = 115200  # Changed from baud_rate to match PySerial standard
    bytesize: int = 8  # Changed from data_bits to match PySerial standard
    stopbits: float = 1  # Changed from stop_bits to match PySerial standard
    parity: str = "N"  # Changed from "none" to match PySerial standard
    timeout: float = 1.0  # This is read timeout
    rtscts: bool = False  # Hardware flow control
    xonxoff: bool = False  # Software flow control


class SerialInputSource(InputSource):
    """Serial input source for GNSS receivers.

    Provides RTCM data reading from GNSS receivers connected via serial ports,
    USB-to-serial adapters, or direct UART connections. Supports standard
    serial configuration options and automatic reconnection.
    """

    def __init__(self, config: SerialConfig):
        """Initialize serial input source.

        Args:
            config: Serial port configuration

        Raises:
            InputSourceError: If PySerial is not available
        """
        if not _pyserial_available or serial is None:
            raise InputSourceError(
                "PySerial library not available. Install with: pip install pyserial"
            )

        super().__init__("Serial")
        self.config = config
        self.serial_port: Any = None  # serial.Serial | None when available

        # Validate configuration
        self._validate_config()

        logger.info(
            f"Initialized serial input source: {config.port} @ {config.baudrate} baud"
        )

    def connect(self) -> bool:
        """Connect to serial port.

        Returns:
            True if connection successful

        Raises:
            InputSourceError: If serial port configuration is invalid
        """
        if self.is_connected:
            logger.debug("Serial port already connected")
            return True

        if serial is None:
            raise InputSourceError("PySerial not available")

        try:
            logger.info(f"Connecting to serial port {self.config.port}")

            # Create and configure serial port using PySerial standard parameters
            self.serial_port = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.bytesize,
                parity=self.config.parity,
                stopbits=self.config.stopbits,
                timeout=self.config.timeout,
                rtscts=self.config.rtscts,
                xonxoff=self.config.xonxoff,
                exclusive=True,  # Prevent other processes from accessing the port
            )

            # Verify port is open
            if not self.serial_port.is_open:
                self.serial_port.open()

            # Clear any existing data in buffers
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

            # Test basic port functionality
            if not self._test_port_health():
                raise InputSourceError("Serial port health check failed")

            self._update_connection_stats(True)
            return True

        except serial.SerialException as e:
            error = InputSourceError(f"Serial port connection failed: {e}")
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error
        except Exception as e:
            error = InputSourceError(f"Unexpected serial connection error: {e}")
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read RTCM data from serial port.

        Args:
            timeout: Read timeout in seconds (uses config default if None)

        Returns:
            Raw RTCM data bytes if available, None if no data or error
        """
        if not self.is_connected or not self.serial_port:
            return None

        if serial is None:
            return None

        try:
            # Use provided timeout or fall back to config timeout
            read_timeout = timeout if timeout is not None else self.config.timeout

            # Temporarily adjust serial port timeout if different
            original_timeout = self.serial_port.timeout
            if read_timeout != original_timeout:
                self.serial_port.timeout = read_timeout

            # Check how much data is available
            bytes_available = self.serial_port.in_waiting

            if bytes_available == 0:
                # No data available, return None (not an error)
                self._update_read_stats(None)
                return None

            # Read available data (up to reasonable limit)
            max_read_size = min(bytes_available, 8192)  # Limit to 8KB per read
            data = self.serial_port.read(max_read_size)

            # Restore original timeout if we changed it
            if read_timeout != original_timeout:
                self.serial_port.timeout = original_timeout

            if data:
                # pyserial returns bytes but is not fully typed; the runtime
                # type is always bytes so we cast for mypy strict.
                data_bytes: bytes = bytes(data)
                self._update_read_stats(data_bytes)
                logger.debug(f"Read {len(data_bytes)} bytes from serial port")
                return data_bytes
            else:
                # No data read (timeout or port closed)
                self._update_read_stats(None)
                return None

        except serial.SerialException as e:
            error = InputSourceError(f"Serial read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None
        except Exception as e:
            error = InputSourceError(f"Unexpected serial read error: {e}")
            self._update_read_stats(None, error)
            self._set_error_state(error)
            return None

    def disconnect(self) -> None:
        """Disconnect from serial port and cleanup resources."""
        logger.info("Disconnecting from serial port")

        if self.serial_port:
            try:
                if self.serial_port.is_open:
                    self.serial_port.close()
            except Exception as e:
                logger.warning(f"Error closing serial port: {e}")
            finally:
                self.serial_port = None

        self._connected = False
        self.stats.connected_since = None
        logger.info("Serial port disconnected")

    def get_connection_info(self) -> dict[str, Any]:
        """Get serial port connection information.

        Returns:
            Dictionary with serial port details
        """
        info = {
            "port": self.config.port,
            "baudrate": self.config.baudrate,
            "bytesize": self.config.bytesize,
            "stopbits": self.config.stopbits,
            "parity": self.config.parity,
        }

        if self.serial_port and self.is_connected:
            info.update(
                {
                    "is_open": self.serial_port.is_open,
                    "in_waiting": self.serial_port.in_waiting,
                    "out_waiting": self.serial_port.out_waiting,
                }
            )

        return info

    def list_available_ports(self) -> list[dict[str, Any]]:
        """List all available serial ports on the system.

        Returns:
            List of dictionaries with port information
        """
        if not _pyserial_available or serial is None:
            return []

        ports: list[dict[str, Any]] = []
        try:
            # Assert serial is not None to help type checker
            assert serial is not None
            for port_info in serial.tools.list_ports.comports():
                port_dict = {
                    "device": port_info.device,
                    "name": port_info.name,
                    "description": port_info.description,
                    "manufacturer": port_info.manufacturer,
                    "product": port_info.product,
                    "vid": port_info.vid,
                    "pid": port_info.pid,
                }
                ports.append(port_dict)
        except Exception as e:
            logger.warning(f"Failed to list serial ports: {e}")

        return ports

    def _validate_config(self) -> None:
        """Validate serial port configuration.

        Raises:
            InputSourceError: If configuration is invalid
        """
        if not self.config.port:
            raise InputSourceError("Serial port must be specified")

        if self.config.baudrate <= 0:
            raise InputSourceError(f"Invalid baud rate: {self.config.baudrate}")

        if self.config.bytesize not in [5, 6, 7, 8]:
            raise InputSourceError(f"Invalid data bits: {self.config.bytesize}")

        if self.config.stopbits not in [1, 1.5, 2]:
            raise InputSourceError(f"Invalid stop bits: {self.config.stopbits}")

        valid_parity = ["N", "E", "O", "M", "S"]
        if self.config.parity not in valid_parity:
            raise InputSourceError(
                f"Invalid parity '{self.config.parity}', must be one of: {valid_parity}"
            )

        if self.config.timeout <= 0:
            raise InputSourceError(f"Invalid timeout: {self.config.timeout}")

    def _test_port_health(self) -> bool:
        """Test basic serial port health.

        Returns:
            True if port appears healthy
        """
        if not self.serial_port or not self.serial_port.is_open:
            return False

        try:
            # Test basic port operations
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

            # Check if we can query port status
            _ = self.serial_port.in_waiting
            _ = self.serial_port.out_waiting

            return True
        except Exception as e:
            logger.warning(f"Serial port health check failed: {e}")
            return False

    def get_port_statistics(self) -> dict[str, Any]:
        """Get detailed port statistics and status.

        Returns:
            Dictionary with detailed port information
        """
        stats = {
            "config": {
                "port": self.config.port,
                "baudrate": self.config.baudrate,
                "bytesize": self.config.bytesize,
                "stopbits": self.config.stopbits,
                "parity": self.config.parity,
            },
            "connection": {
                "connected": self.is_connected,
                "connection_attempts": self.stats.connection_attempts,
                "successful_connections": self.stats.successful_connections,
                "connection_failures": self.stats.connection_failures,
                "connected_since": self.stats.connected_since,
            },
            "data_flow": {
                "bytes_read": self.stats.bytes_read,
                "messages_read": self.stats.messages_read,
                "read_errors": self.stats.read_errors,
                "last_read_time": self.stats.last_read_time,
            },
            "last_error": str(self.last_error) if self.last_error else None,
        }

        if self.serial_port and self.is_connected:
            try:
                stats["port_status"] = {
                    "is_open": self.serial_port.is_open,
                    "in_waiting": self.serial_port.in_waiting,
                    "out_waiting": self.serial_port.out_waiting,
                    "cts": self.serial_port.cts,
                    "dsr": self.serial_port.dsr,
                    "ri": self.serial_port.ri,
                    "cd": self.serial_port.cd,
                }
            except Exception as e:
                stats["port_status"] = {"error": str(e)}

        return stats
