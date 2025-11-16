"""Mock input sources for testing SP-Base-Relay input source functionality.

This module provides mock input source implementations that generate synthetic
RTCM data for testing purposes without requiring actual hardware connections.
"""

import logging
import random
import time
import threading
from typing import Any
from dataclasses import dataclass

from src.sp_base_relay.core.input_sources.base_input import InputSource
from src.sp_base_relay.exceptions import InputSourceError
from .rtcm_generator import RTCMGenerator


logger = logging.getLogger(__name__)


@dataclass
class MockInputConfig:
    """Configuration for mock input sources."""

    data_rate_bps: int = 1000  # Bytes per second to generate
    message_interval: float = 1.0  # Seconds between messages
    connection_delay: float = 0.1  # Simulated connection delay
    failure_rate: float = 0.0  # Probability of read failures (0.0 - 1.0)
    max_message_size: int = 1500  # Maximum RTCM message size
    should_fail_connection: bool = False  # Force connection failures
    should_disconnect_randomly: bool = False  # Random disconnections
    disconnect_probability: float = 0.01  # Probability per read


class MockSerialInputSource(InputSource):
    """Mock serial input source for testing.

    Generates synthetic RTCM data at configurable rates and intervals.
    Simulates serial port behavior including connection delays and failures.
    """

    def __init__(self, config: MockInputConfig):
        """Initialize mock serial input source.

        Args:
            config: Mock configuration parameters
        """
        super().__init__("MockSerial")
        self.config = config
        self.rtcm_generator = RTCMGenerator()

        # Simulation state
        self._last_message_time = 0.0
        self._message_count = 0
        self._should_disconnect = False

        logger.info(f"Initialized mock serial input: {config.data_rate_bps} bps")

    def connect(self) -> bool:
        """Simulate serial port connection.

        Returns:
            True if connection successful
        """
        if self.is_connected:
            return True

        logger.info("Mock serial: Attempting connection")

        # Simulate connection delay
        if self.config.connection_delay > 0:
            time.sleep(self.config.connection_delay)

        # Simulate connection failure if configured
        if self.config.should_fail_connection:
            error = InputSourceError("Mock serial connection failed (simulated)")
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error

        self._update_connection_stats(True)
        self._last_message_time = time.time()
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Generate and return synthetic RTCM data.

        Args:
            timeout: Read timeout (ignored in mock)

        Returns:
            Synthetic RTCM data or None
        """
        if not self.is_connected:
            return None

        # Simulate random disconnection
        if (
            self.config.should_disconnect_randomly
            and random.random() < self.config.disconnect_probability
        ):
            logger.warning("Mock serial: Random disconnection")
            self._should_disconnect = True
            self._set_error_state(InputSourceError("Random disconnection (simulated)"))
            return None

        # Check if we should disconnect
        if self._should_disconnect:
            return None

        # Simulate read failures
        if random.random() < self.config.failure_rate:
            error = InputSourceError("Mock serial read error (simulated)")
            self._update_read_stats(None, error)
            return None

        current_time = time.time()

        # Check if it's time for next message
        if current_time - self._last_message_time < self.config.message_interval:
            self._update_read_stats(None)  # No data available yet
            return None

        # Generate RTCM message
        message_size = min(
            random.randint(100, self.config.max_message_size),
            self.config.data_rate_bps,  # Limit by data rate
        )

        rtcm_data = self.rtcm_generator.generate_rtcm_message(
            message_type=random.choice([1005, 1077, 1087, 1097]), size=message_size
        )

        self._last_message_time = current_time
        self._message_count += 1

        self._update_read_stats(rtcm_data)
        logger.debug(
            f"Mock serial: Generated {len(rtcm_data)} bytes (message #{self._message_count})"
        )

        return rtcm_data

    def disconnect(self) -> None:
        """Simulate disconnection."""
        logger.info("Mock serial: Disconnecting")
        self._connected = False
        self.stats.connected_since = None
        self._should_disconnect = False

    def get_connection_info(self) -> dict[str, Any]:
        """Get mock connection information."""
        return {
            "type": "mock_serial",
            "data_rate_bps": self.config.data_rate_bps,
            "message_interval": self.config.message_interval,
            "failure_rate": self.config.failure_rate,
            "messages_generated": self._message_count,
            "last_message_time": self._last_message_time,
        }

    def trigger_disconnection(self) -> None:
        """Trigger a simulated disconnection on next read."""
        logger.info("Mock serial: Disconnection triggered")
        self._should_disconnect = True


class MockTCPInputSource(InputSource):
    """Mock TCP input source for testing.

    Simulates RTKBase str2str_tcp service behavior for testing
    TCP input source functionality without requiring actual service.
    """

    def __init__(self, config: MockInputConfig):
        """Initialize mock TCP input source.

        Args:
            config: Mock configuration parameters
        """
        super().__init__("MockTCP")
        self.config = config
        self.rtcm_generator = RTCMGenerator()

        # Simulation state
        self._last_message_time = 0.0
        self._message_count = 0
        self._connection_refused = False
        self._should_disconnect = False

        logger.info(f"Initialized mock TCP input: {config.data_rate_bps} bps")

    def connect(self) -> bool:
        """Simulate TCP connection.

        Returns:
            True if connection successful
        """
        if self.is_connected:
            return True

        logger.info("Mock TCP: Attempting connection")

        # Simulate connection delay
        if self.config.connection_delay > 0:
            time.sleep(self.config.connection_delay)

        # Simulate connection refused
        if self._connection_refused or self.config.should_fail_connection:
            error = InputSourceError("Mock TCP connection refused (simulated)")
            self._update_connection_stats(False)
            self._set_error_state(error)
            raise error

        self._update_connection_stats(True)
        self._last_message_time = time.time()
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Generate and return synthetic RTCM data over TCP.

        Args:
            timeout: Read timeout (ignored in mock)

        Returns:
            Synthetic RTCM data or None
        """
        if not self.is_connected:
            return None

        # Simulate random disconnection
        if (
            self.config.should_disconnect_randomly
            and random.random() < self.config.disconnect_probability
        ):
            logger.warning("Mock TCP: Random disconnection")
            self._should_disconnect = True
            self._set_error_state(
                InputSourceError("TCP connection closed by peer (simulated)")
            )
            return None

        # Check if we should disconnect
        if self._should_disconnect:
            return None

        # Simulate read failures/timeouts
        if random.random() < self.config.failure_rate:
            # For TCP, sometimes return None (timeout), sometimes error
            if random.random() < 0.5:
                self._update_read_stats(None)  # Timeout
                return None
            else:
                error = InputSourceError("Mock TCP read error (simulated)")
                self._update_read_stats(None, error)
                return None

        current_time = time.time()

        # Check if it's time for next message
        if current_time - self._last_message_time < self.config.message_interval:
            self._update_read_stats(None)  # No data available yet
            return None

        # Generate multiple small messages or one large message
        if random.random() < 0.7:  # 70% chance of single message
            message_size = random.randint(200, self.config.max_message_size)
            rtcm_data = self.rtcm_generator.generate_rtcm_message(
                message_type=random.choice([1005, 1074, 1084, 1094, 1124]),
                size=message_size,
            )
        else:  # 30% chance of multiple messages in one read
            messages: list[bytes] = []
            for _ in range(random.randint(2, 4)):
                message_size = random.randint(100, 800)
                messages.append(
                    self.rtcm_generator.generate_rtcm_message(
                        message_type=random.choice([1077, 1087, 1097, 1127]),
                        size=message_size,
                    )
                )
            rtcm_data = b"".join(messages)

        self._last_message_time = current_time
        self._message_count += 1

        self._update_read_stats(rtcm_data)
        logger.debug(
            f"Mock TCP: Generated {len(rtcm_data)} bytes (message #{self._message_count})"
        )

        return rtcm_data

    def disconnect(self) -> None:
        """Simulate TCP disconnection."""
        logger.info("Mock TCP: Disconnecting")
        self._connected = False
        self.stats.connected_since = None
        self._should_disconnect = False

    def get_connection_info(self) -> dict[str, Any]:
        """Get mock TCP connection information."""
        return {
            "type": "mock_tcp",
            "host": "mock_localhost",
            "port": 5015,
            "data_rate_bps": self.config.data_rate_bps,
            "message_interval": self.config.message_interval,
            "failure_rate": self.config.failure_rate,
            "messages_generated": self._message_count,
            "last_message_time": self._last_message_time,
        }

    def set_connection_refused(self, refused: bool) -> None:
        """Configure connection refused simulation.

        Args:
            refused: Whether to refuse connections
        """
        self._connection_refused = refused
        logger.info(f"Mock TCP: Connection refused set to {refused}")

    def trigger_disconnection(self) -> None:
        """Trigger a simulated disconnection on next read."""
        logger.info("Mock TCP: Disconnection triggered")
        self._should_disconnect = True


class MockInputSourceFactory:
    """Factory for creating mock input sources for testing."""

    @staticmethod
    def create_fast_serial_source() -> MockSerialInputSource:
        """Create a fast, reliable mock serial source for testing.

        Returns:
            Fast mock serial input source
        """
        config = MockInputConfig(
            data_rate_bps=2000,
            message_interval=0.5,
            connection_delay=0.05,
            failure_rate=0.0,
            max_message_size=1200,
        )
        return MockSerialInputSource(config)

    @staticmethod
    def create_slow_serial_source() -> MockSerialInputSource:
        """Create a slow mock serial source for testing.

        Returns:
            Slow mock serial input source
        """
        config = MockInputConfig(
            data_rate_bps=500,
            message_interval=2.0,
            connection_delay=0.2,
            failure_rate=0.05,
            max_message_size=800,
        )
        return MockSerialInputSource(config)

    @staticmethod
    def create_unreliable_serial_source() -> MockSerialInputSource:
        """Create an unreliable mock serial source for error testing.

        Returns:
            Unreliable mock serial input source
        """
        config = MockInputConfig(
            data_rate_bps=1000,
            message_interval=1.0,
            connection_delay=0.1,
            failure_rate=0.2,
            should_disconnect_randomly=True,
            disconnect_probability=0.05,
            max_message_size=1000,
        )
        return MockSerialInputSource(config)

    @staticmethod
    def create_tcp_source() -> MockTCPInputSource:
        """Create a reliable mock TCP source for testing.

        Returns:
            Reliable mock TCP input source
        """
        config = MockInputConfig(
            data_rate_bps=3000,
            message_interval=0.3,
            connection_delay=0.1,
            failure_rate=0.02,
            max_message_size=2000,
        )
        return MockTCPInputSource(config)

    @staticmethod
    def create_unavailable_tcp_source() -> MockTCPInputSource:
        """Create a mock TCP source that refuses connections.

        Returns:
            Mock TCP source that refuses connections
        """
        config = MockInputConfig(should_fail_connection=True)
        tcp_source = MockTCPInputSource(config)
        tcp_source.set_connection_refused(True)
        return tcp_source

    @staticmethod
    def create_high_throughput_source() -> MockTCPInputSource:
        """Create a high-throughput mock TCP source for performance testing.

        Returns:
            High-throughput mock TCP input source
        """
        config = MockInputConfig(
            data_rate_bps=10000,
            message_interval=0.1,
            connection_delay=0.05,
            failure_rate=0.01,
            max_message_size=4000,
        )
        return MockTCPInputSource(config)


class StreamingMockInputSource(InputSource):
    """Mock input source that streams continuous data.

    Provides continuous data streaming for testing pipeline throughput
    and performance under sustained load.
    """

    def __init__(self, bytes_per_second: int = 2000):
        """Initialize streaming mock input source.

        Args:
            bytes_per_second: Target data rate in bytes per second
        """
        super().__init__("MockStreaming")
        self.bytes_per_second = bytes_per_second
        self.rtcm_generator = RTCMGenerator()

        # Streaming state
        self._data_buffer = bytearray()
        self._last_generation_time = 0.0
        self._total_generated = 0
        self._generation_thread: threading.Thread | None = None
        self._stop_generation = threading.Event()

        logger.info(f"Initialized streaming mock input: {bytes_per_second} bytes/sec")

    def connect(self) -> bool:
        """Start streaming data generation."""
        if self.is_connected:
            return True

        self._update_connection_stats(True)
        self._last_generation_time = time.time()

        # Start background data generation
        self._stop_generation.clear()
        self._generation_thread = threading.Thread(
            target=self._generate_data_continuously,
            name="MockStreamingGenerator",
            daemon=True,
        )
        self._generation_thread.start()

        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        """Read from continuously generated data buffer.

        Args:
            timeout: Read timeout (ignored)

        Returns:
            Buffered RTCM data or None if no data
        """
        if not self.is_connected:
            return None

        if not self._data_buffer:
            return None

        # Read up to 2KB at a time
        read_size = min(len(self._data_buffer), 2048)
        data = bytes(self._data_buffer[:read_size])
        del self._data_buffer[:read_size]

        if data:
            self._update_read_stats(data)
            logger.debug(f"Mock streaming: Read {len(data)} bytes")

        return data

    def disconnect(self) -> None:
        """Stop streaming and disconnect."""
        logger.info("Mock streaming: Disconnecting")

        # Stop data generation
        self._stop_generation.set()
        if self._generation_thread and self._generation_thread.is_alive():
            self._generation_thread.join(timeout=1.0)

        self._connected = False
        self.stats.connected_since = None
        self._data_buffer.clear()

    def get_connection_info(self) -> dict[str, Any]:
        """Get streaming mock connection information."""
        return {
            "type": "mock_streaming",
            "bytes_per_second": self.bytes_per_second,
            "buffer_size": len(self._data_buffer),
            "total_generated": self._total_generated,
        }

    def _generate_data_continuously(self) -> None:
        """Background thread for continuous data generation."""
        logger.debug("Mock streaming: Started data generation thread")

        try:
            while not self._stop_generation.is_set():
                current_time = time.time()
                time_elapsed = current_time - self._last_generation_time

                if time_elapsed >= 0.1:  # Generate data every 100ms
                    bytes_to_generate = int(self.bytes_per_second * time_elapsed)

                    if bytes_to_generate > 0:
                        # Generate RTCM messages to fill the target bytes
                        while bytes_to_generate > 0:
                            message_size = min(
                                bytes_to_generate, random.randint(200, 1200)
                            )
                            rtcm_data = self.rtcm_generator.generate_rtcm_message(
                                message_type=random.choice([1077, 1087, 1097, 1127]),
                                size=message_size,
                            )

                            self._data_buffer.extend(rtcm_data)
                            self._total_generated += len(rtcm_data)
                            bytes_to_generate -= len(rtcm_data)

                    self._last_generation_time = current_time

                # Sleep briefly to avoid busy waiting
                time.sleep(0.05)

        except Exception as e:
            logger.error(f"Mock streaming generation error: {e}")
        finally:
            logger.debug("Mock streaming: Data generation thread stopped")
