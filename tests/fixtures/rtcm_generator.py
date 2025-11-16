"""Synthetic RTCM data generator for testing.

This module provides utilities to generate synthetic RTCM 3.x messages
for testing purposes. The generated data follows the basic RTCM structure
but contains synthetic positioning data.
"""

import struct
import time
from dataclasses import dataclass


@dataclass
class RTCMMessage:
    """Represents an RTCM 3.x message."""

    message_type: int
    station_id: int
    payload: bytes
    length: int

    def to_bytes(self) -> bytes:
        """Convert message to RTCM binary format.

        Returns:
            Binary RTCM message
        """
        # RTCM 3.x frame format:
        # Preamble (0xD3) + Reserved bits + Length + Payload + CRC

        # Build header
        header = bytearray()
        header.append(0xD3)  # Preamble

        # Length field (10 bits) + reserved bits (6 bits)
        length_field = (self.length & 0x3FF) << 6
        header.extend(struct.pack(">H", length_field))

        # Build complete message
        message = header + self.payload

        # Calculate CRC24Q
        crc = self._calculate_crc24q(message)
        message.extend(struct.pack(">I", crc)[:3])  # Only use 3 bytes of CRC

        return bytes(message)

    def _calculate_crc24q(self, data: bytes | bytearray) -> int:
        """Calculate CRC24Q checksum for RTCM data.

        Args:
            data: Data to calculate CRC for

        Returns:
            24-bit CRC value
        """
        # CRC24Q polynomial: 0x1864CFB
        crc = 0
        polynomial = 0x1864CFB

        for byte in data:
            crc ^= byte << 16
            for _ in range(8):
                if crc & 0x800000:
                    crc = (crc << 1) ^ polynomial
                else:
                    crc <<= 1
                crc &= 0xFFFFFF

        return crc


class RTCMGenerator:
    """Generator for synthetic RTCM messages."""

    def __init__(self, station_id: int = 1001):
        """Initialize RTCM generator.

        Args:
            station_id: Reference station ID
        """
        self.station_id = station_id
        self._sequence = 0

    def generate_type_1005(self) -> RTCMMessage:
        """Generate RTCM Type 1005 message (Stationary RTK Reference Station ARP).

        Returns:
            RTCM 1005 message with synthetic coordinates
        """
        payload = bytearray()

        # Message type (12 bits)
        message_type = 1005

        # Station ID (12 bits)
        station_id = self.station_id & 0xFFF

        # ITRS Realization Year (6 bits) - use current year - 1980
        itrs_year = (2024 - 1980) & 0x3F

        # GPS Indicator (1 bit), GLONASS Indicator (1 bit), Reserved (2 bits)
        indicators = 0b1100  # GPS=1, GLONASS=1, Reserved=00

        # ECEF-X (38 bits signed) - synthetic coordinate
        ecef_x = int(-2434804.5210 * 10000) & 0x3FFFFFFFFF  # ~38 bits

        # ECEF-Y (38 bits signed) - synthetic coordinate
        ecef_y = int(-4707348.0500 * 10000) & 0x3FFFFFFFFF

        # ECEF-Z (38 bits signed) - synthetic coordinate
        ecef_z = int(3546429.8890 * 10000) & 0x3FFFFFFFFF

        # Build payload using bit packing
        bit_buffer = 0
        bit_count = 0

        def add_bits(value: int, num_bits: int) -> None:
            nonlocal bit_buffer, bit_count
            bit_buffer = (bit_buffer << num_bits) | (value & ((1 << num_bits) - 1))
            bit_count += num_bits

            while bit_count >= 8:
                payload.append((bit_buffer >> (bit_count - 8)) & 0xFF)
                bit_count -= 8
                bit_buffer &= (1 << bit_count) - 1

        # Pack all fields
        add_bits(message_type, 12)
        add_bits(station_id, 12)
        add_bits(itrs_year, 6)
        add_bits(indicators, 4)
        add_bits(ecef_x, 38)
        add_bits(ecef_y, 38)
        add_bits(ecef_z, 38)

        # Pad to byte boundary
        if bit_count > 0:
            add_bits(0, 8 - bit_count)

        return RTCMMessage(
            message_type=1005,
            station_id=self.station_id,
            payload=bytes(payload),
            length=len(payload),
        )

    def generate_type_1077(self) -> RTCMMessage:
        """Generate RTCM Type 1077 message (GPS MSM7).

        Returns:
            RTCM 1077 message with synthetic GPS observations
        """
        payload = bytearray()
        bit_buffer = 0
        bit_count = 0

        def add_bits(value: int, num_bits: int) -> None:
            nonlocal bit_buffer, bit_count
            bit_buffer = (bit_buffer << num_bits) | (value & ((1 << num_bits) - 1))
            bit_count += num_bits

            while bit_count >= 8:
                payload.append((bit_buffer >> (bit_count - 8)) & 0xFF)
                bit_count -= 8
                bit_buffer &= (1 << bit_count) - 1

        # Message type (12 bits)
        add_bits(1077, 12)

        # Station ID (12 bits)
        add_bits(self.station_id & 0xFFF, 12)

        # GPS Epoch Time (30 bits) - milliseconds in GPS week
        gps_time = int(time.time() * 1000) % (7 * 24 * 3600 * 1000)
        add_bits(gps_time & 0x3FFFFFFF, 30)

        # Multiple Message Bit (1 bit)
        add_bits(0, 1)

        # Issue of Data Station (3 bits)
        add_bits(0, 3)

        # Reserved (7 bits)
        add_bits(0, 7)

        # Clock Steering Indicator (2 bits)
        add_bits(0, 2)

        # External Clock Indicator (2 bits)
        add_bits(0, 2)

        # Smoothing Divergence (1 bit)
        add_bits(0, 1)

        # Smoothing Interval (3 bits)
        add_bits(0, 3)

        # Satellite mask (64 bits) - simulate 8 satellites
        satellite_mask = 0xFF00000000000000  # Satellites 1-8
        add_bits(satellite_mask, 64)

        # Signal mask (32 bits) - simulate L1C/A and L2P signals
        signal_mask = 0xC0000000  # Signals 1 and 2
        add_bits(signal_mask, 32)

        # Cell mask based on satellite and signal masks
        # For simplicity, assume all combinations exist
        cell_mask = 0xFFFF  # 8 satellites * 2 signals = 16 cells

        # Satellite data (for each satellite in mask)
        for sat in range(8):
            if satellite_mask & (1 << (63 - sat)):
                # Rough range (8 bits) in milliseconds
                add_bits(128 + sat * 2, 8)

        # Signal data (for each signal in mask)
        for sig in range(2):
            if signal_mask & (1 << (31 - sig)):
                # Fine PhaseRange (15 bits)
                add_bits(16384 + sig * 1000, 15)
                # Lock time (4 bits)
                add_bits(15, 4)
                # Half-cycle ambiguity (1 bit)
                add_bits(0, 1)
                # CNR (6 bits) - 45 dB-Hz
                add_bits(45, 6)

        # Cell data (for each cell)
        for cell in range(16):
            if cell_mask & (1 << (15 - cell)):
                # Fine PseudoRange (15 bits)
                add_bits(16384 + cell * 100, 15)
                # Fine PhaseRange (22 bits)
                add_bits(2097152 + cell * 1000, 22)
                # Lock time (4 bits)
                add_bits(15, 4)
                # Half-cycle ambiguity (1 bit)
                add_bits(0, 1)
                # CNR (6 bits)
                add_bits(45 + cell, 6)
                # Fine PhaseRange rate (15 bits)
                add_bits(16384, 15)

        # Pad to byte boundary
        if bit_count > 0:
            add_bits(0, 8 - bit_count)

        return RTCMMessage(
            message_type=1077,
            station_id=self.station_id,
            payload=bytes(payload),
            length=len(payload),
        )

    def generate_type_1230(self) -> RTCMMessage:
        """Generate RTCM Type 1230 message (GLONASS L1 and L2 Code-Phase Biases).

        Returns:
            RTCM 1230 message with synthetic GLONASS bias data
        """
        payload = bytearray()
        bit_buffer = 0
        bit_count = 0

        def add_bits(value: int, num_bits: int) -> None:
            nonlocal bit_buffer, bit_count
            bit_buffer = (bit_buffer << num_bits) | (value & ((1 << num_bits) - 1))
            bit_count += num_bits

            while bit_count >= 8:
                payload.append((bit_buffer >> (bit_count - 8)) & 0xFF)
                bit_count -= 8
                bit_buffer &= (1 << bit_count) - 1

        # Message type (12 bits)
        add_bits(1230, 12)

        # Station ID (12 bits)
        add_bits(self.station_id & 0xFFF, 12)

        # L1 C/A Code-Phase Bias Indicator (1 bit)
        add_bits(1, 1)

        # L1 P Code-Phase Bias Indicator (1 bit)
        add_bits(1, 1)

        # L2 C/A Code-Phase Bias Indicator (1 bit)
        add_bits(0, 1)

        # L2 P Code-Phase Bias Indicator (1 bit)
        add_bits(1, 1)

        # L1 C/A Code-Phase Bias (16 bits) - in 0.02 m units
        add_bits(12345, 16)

        # L1 P Code-Phase Bias (16 bits)
        add_bits(23456, 16)

        # L2 P Code-Phase Bias (16 bits)
        add_bits(34567, 16)

        # Pad to byte boundary
        if bit_count > 0:
            add_bits(0, 8 - bit_count)

        return RTCMMessage(
            message_type=1230,
            station_id=self.station_id,
            payload=bytes(payload),
            length=len(payload),
        )

    def generate_random_message(self) -> RTCMMessage:
        """Generate a random RTCM message type.

        Returns:
            Random RTCM message
        """
        import random

        message_types = [
            self.generate_type_1005,
            self.generate_type_1077,
            self.generate_type_1230,
        ]

        return random.choice(message_types)()

    def generate_rtcm_message(
        self, message_type: int = 1005, size: int = 1024
    ) -> bytes:
        """Generate an RTCM message of specified type and approximate size.

        Args:
            message_type: RTCM message type (1005, 1077, 1087, 1097, etc.)
            size: Target size in bytes (approximate)

        Returns:
            Binary RTCM message data
        """
        # Generate message based on type
        if message_type == 1005:
            msg = self.generate_type_1005()
        elif message_type in (1077, 1087, 1097):
            msg = self.generate_type_1077()
        elif message_type == 1230:
            msg = self.generate_type_1230()
        else:
            # Default to type 1077 for unknown types
            msg = self.generate_type_1077()

        return msg.to_bytes()

    def generate_stream(self, count: int = 10, delay: float = 1.0) -> list[bytes]:
        """Generate a stream of RTCM messages.

        Args:
            count: Number of messages to generate
            delay: Delay between messages (for timestamp simulation)

        Returns:
            List of binary RTCM messages
        """
        messages: list[bytes] = []

        for i in range(count):
            if i % 5 == 0:
                # Every 5th message is Type 1005 (station position)
                msg = self.generate_type_1005()
            elif i % 3 == 0:
                # Every 3rd message is Type 1077 (GPS observations)
                msg = self.generate_type_1077()
            else:
                # Random message
                msg = self.generate_random_message()

            messages.append(msg.to_bytes())

            # Simulate timing
            if delay > 0 and i < count - 1:
                time.sleep(delay)

        return messages

    def generate_continuous_data(self, size_bytes: int = 1024) -> bytes:
        """Generate continuous RTCM data stream of specified size.

        Args:
            size_bytes: Target size in bytes

        Returns:
            Continuous binary RTCM data
        """
        data = bytearray()

        while len(data) < size_bytes:
            msg = self.generate_random_message()
            msg_bytes = msg.to_bytes()
            data.extend(msg_bytes)

        # Truncate to exact size
        return bytes(data[:size_bytes])


# Convenience functions for testing
def create_test_rtcm_data(size_kb: int = 1) -> bytes:
    """Create test RTCM data of specified size.

    Args:
        size_kb: Size in kilobytes

    Returns:
        Binary RTCM data
    """
    generator = RTCMGenerator(station_id=1001)
    return generator.generate_continuous_data(size_kb * 1024)


def create_rtcm_message_stream(message_count: int = 10) -> list[bytes]:
    """Create a stream of individual RTCM messages.

    Args:
        message_count: Number of messages to generate

    Returns:
        List of individual RTCM messages
    """
    generator = RTCMGenerator(station_id=1001)
    return generator.generate_stream(message_count, delay=0)


def get_sample_rtcm_message() -> bytes:
    """Get a single sample RTCM message for testing.

    Returns:
        Single RTCM message
    """
    generator = RTCMGenerator(station_id=1001)
    msg = generator.generate_type_1005()
    return msg.to_bytes()


if __name__ == "__main__":
    # Demo usage
    generator = RTCMGenerator(station_id=1001)

    # Generate different message types
    msg_1005 = generator.generate_type_1005()
    msg_1077 = generator.generate_type_1077()
    msg_1230 = generator.generate_type_1230()

    print(f"Type 1005 message: {len(msg_1005.to_bytes())} bytes")
    print(f"Type 1077 message: {len(msg_1077.to_bytes())} bytes")
    print(f"Type 1230 message: {len(msg_1230.to_bytes())} bytes")

    # Generate continuous data
    test_data = generator.generate_continuous_data(2048)
    print(f"Generated {len(test_data)} bytes of continuous RTCM data")
