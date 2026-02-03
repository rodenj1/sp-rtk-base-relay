"""Mock serial port for testing serial input sources.

Provides a mock implementation of pyserial.Serial for testing serial input
functionality without requiring actual hardware.
"""

import time
from collections.abc import Iterator


class MockSerialPort:
    """Mock serial port simulating pyserial.Serial behavior."""

    def __init__(
        self,
        port: str = "/dev/ttyUSB0",
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        timeout: float | None = None,
        rtscts: bool = False,
        xonxoff: bool = False,
        exclusive: bool = False,
    ):
        """Initialize mock serial port.

        Args:
            port: Serial port device path
            baudrate: Baud rate
            bytesize: Number of data bits
            parity: Parity setting (N/E/O/M/S)
            stopbits: Number of stop bits
            timeout: Read timeout in seconds
            rtscts: Enable hardware flow control
            xonxoff: Enable software flow control
            exclusive: Whether to open port exclusively
        """
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity
        self.stopbits = stopbits
        self.timeout = timeout
        self.rtscts = rtscts
        self.xonxoff = xonxoff
        self.exclusive = exclusive

        self._is_open = False
        self._in_buffer: bytes = b""
        self._out_buffer: bytes = b""

        # Control flags for testing
        self.raise_on_open = False
        self.raise_on_read = False
        self.raise_on_close = False
        self.close_immediately = False

        # Modem status lines
        self._cts = True
        self._dsr = True
        self._ri = False
        self._cd = True

    @property
    def is_open(self) -> bool:
        """Check if port is open."""
        return self._is_open

    @property
    def in_waiting(self) -> int:
        """Get number of bytes waiting to be read."""
        return len(self._in_buffer)

    @property
    def out_waiting(self) -> int:
        """Get number of bytes waiting to be written."""
        return len(self._out_buffer)

    @property
    def cts(self) -> bool:
        """Clear To Send modem status line."""
        return self._cts

    @property
    def dsr(self) -> bool:
        """Data Set Ready modem status line."""
        return self._dsr

    @property
    def ri(self) -> bool:
        """Ring Indicator modem status line."""
        return self._ri

    @property
    def cd(self) -> bool:
        """Carrier Detect modem status line."""
        return self._cd

    @property
    def name(self) -> str:
        """Get port name."""
        return self.port

    def open(self) -> None:
        """Open serial port.

        Raises:
            SerialException: If configured to raise on open
        """
        if self.raise_on_open:
            raise SerialException(f"Failed to open port {self.port}")

        self._is_open = True

    def close(self) -> None:
        """Close serial port.

        Raises:
            SerialException: If configured to raise on close
        """
        if self.raise_on_close:
            raise SerialException(f"Failed to close port {self.port}")

        self._is_open = False
        self._in_buffer = b""
        self._out_buffer = b""

    def read(self, size: int = 1) -> bytes:
        """Read bytes from serial port.

        Args:
            size: Number of bytes to read

        Returns:
            Bytes read from buffer

        Raises:
            SerialException: If configured to raise on read
        """
        if self.raise_on_read:
            raise SerialException(f"Read error on port {self.port}")

        if not self._is_open:
            return b""

        if self.close_immediately:
            self._is_open = False
            return b""

        # Simulate timeout if no data available
        if len(self._in_buffer) == 0:
            if self.timeout is not None and self.timeout > 0:
                time.sleep(min(self.timeout, 0.1))  # Simulate partial timeout
            return b""

        # Read requested bytes
        data = self._in_buffer[:size]
        self._in_buffer = self._in_buffer[size:]
        return data

    def write(self, data: bytes) -> int:
        """Write bytes to serial port.

        Args:
            data: Bytes to write

        Returns:
            Number of bytes written
        """
        if not self._is_open:
            raise SerialException(f"Port {self.port} is not open")

        self._out_buffer += data
        return len(data)

    def reset_input_buffer(self) -> None:
        """Clear input buffer."""
        self._in_buffer = b""

    def reset_output_buffer(self) -> None:
        """Clear output buffer."""
        self._out_buffer = b""

    def flush(self) -> None:
        """Flush output buffer."""
        self._out_buffer = b""

    # Test helper methods

    def add_data_to_buffer(self, data: bytes) -> None:
        """Add data to input buffer for testing.

        Args:
            data: Data to add to input buffer
        """
        self._in_buffer += data

    def get_written_data(self) -> bytes:
        """Get data written to output buffer.

        Returns:
            Data from output buffer
        """
        data = self._out_buffer
        self._out_buffer = b""
        return data

    def simulate_disconnect(self) -> None:
        """Simulate port disconnection."""
        self._is_open = False

    def set_modem_lines(
        self,
        cts: bool | None = None,
        dsr: bool | None = None,
        ri: bool | None = None,
        cd: bool | None = None,
    ) -> None:
        """Set modem status lines for testing.

        Args:
            cts: Clear To Send state
            dsr: Data Set Ready state
            ri: Ring Indicator state
            cd: Carrier Detect state
        """
        if cts is not None:
            self._cts = cts
        if dsr is not None:
            self._dsr = dsr
        if ri is not None:
            self._ri = ri
        if cd is not None:
            self._cd = cd


class SerialException(Exception):
    """Mock SerialException to match pyserial."""

    pass


class MockListPortInfo:
    """Mock serial port info for list_ports.comports()."""

    def __init__(
        self,
        device: str,
        name: str = "",
        description: str = "",
        manufacturer: str | None = None,
        product: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
    ):
        """Initialize port info.

        Args:
            device: Device path
            name: Port name
            description: Port description
            manufacturer: Manufacturer name
            product: Product name
            vid: Vendor ID
            pid: Product ID
        """
        self.device = device
        self.name = name
        self.description = description
        self.manufacturer = manufacturer
        self.product = product
        self.vid = vid
        self.pid = pid


class MockListPorts:
    """Mock serial.tools.list_ports module."""

    def __init__(self):
        """Initialize mock list_ports."""
        self._ports: list[MockListPortInfo] = []

    def comports(self) -> Iterator[MockListPortInfo]:
        """Return list of available serial ports.

        Yields:
            Mock port info objects
        """
        return iter(self._ports)

    def add_port(
        self,
        device: str,
        name: str = "",
        description: str = "",
        manufacturer: str | None = None,
        product: str | None = None,
        vid: int | None = None,
        pid: int | None = None,
    ) -> None:
        """Add a port to the list.

        Args:
            device: Device path
            name: Port name
            description: Port description
            manufacturer: Manufacturer name
            product: Product name
            vid: Vendor ID
            pid: Product ID
        """
        port_info = MockListPortInfo(
            device=device,
            name=name,
            description=description,
            manufacturer=manufacturer,
            product=product,
            vid=vid,
            pid=pid,
        )
        self._ports.append(port_info)

    def clear_ports(self) -> None:
        """Clear all ports from the list."""
        self._ports = []


# Parity constants to match pyserial
PARITY_NONE = "N"
PARITY_EVEN = "E"
PARITY_ODD = "O"
PARITY_MARK = "M"
PARITY_SPACE = "S"
