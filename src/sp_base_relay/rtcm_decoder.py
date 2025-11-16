"""RTCM message decoder for extracting message IDs and metadata.

This module provides utilities for parsing RTCM v3 messages to extract
message IDs for metrics tracking. The decoder is designed for minimal
overhead and is used for post-send metrics collection only.
"""

import logging


logger = logging.getLogger(__name__)


class RTCMMessageDecoder:
    """Lightweight RTCM v3 message decoder for metrics collection.

    This decoder extracts message IDs from RTCM v3 frames without performing
    full message validation. It's designed for post-send metrics tracking
    with minimal performance impact.

    RTCM v3 Frame Format:
    - Byte 0: Preamble (0xD3)
    - Bytes 1-2: Reserved (6 bits) + Message Length (10 bits)
    - Bytes 3-4: Message ID (12 bits) + payload start
    - Payload: Variable length
    - CRC: 3 bytes (24 bits)
    """

    @staticmethod
    def extract_message_id(data: bytes) -> int | None:
        """Extract RTCM message ID from message data.

        Args:
            data: Raw RTCM message bytes

        Returns:
            Message ID (0-4095) if valid RTCM v3 frame, None otherwise

        Examples:
            >>> data = b'\\xd3\\x00\\x13\\x3e\\xd0...'  # RTCM 1005
            >>> RTCMMessageDecoder.extract_message_id(data)
            1005
        """
        # Minimum RTCM v3 frame: preamble (1) + length (2) + ID (2) + CRC (3) = 8 bytes
        if len(data) < 8:
            logger.debug(f"RTCM frame too short: {len(data)} bytes")
            return None

        # Check preamble (0xD3)
        if data[0] != 0xD3:
            logger.debug(f"Invalid RTCM preamble: 0x{data[0]:02X}")
            return None

        # Extract message length (10 bits from bytes 1-2)
        # Byte 1: Reserved (6 bits) + Length high 2 bits
        # Byte 2: Length low 8 bits
        length = ((data[1] & 0x03) << 8) | data[2]

        # Validate length
        # RTCM v3 max message length is 1023 bytes (10 bits)
        # Frame should be: 3 (header) + length (payload) + 3 (CRC)
        expected_frame_length = 3 + length + 3
        if len(data) < expected_frame_length:
            logger.debug(
                f"RTCM frame incomplete: got {len(data)} bytes, "
                f"expected {expected_frame_length}"
            )
            return None

        # Extract message ID (12 bits from bytes 3-4)
        # Byte 3: Message ID high 8 bits
        # Byte 4: Message ID low 4 bits + payload start
        message_id = (data[3] << 4) | (data[4] >> 4)

        # Validate message ID range (0-4095 for 12 bits)
        if message_id > 4095:
            logger.debug(f"Invalid RTCM message ID: {message_id}")
            return None

        logger.debug(f"Extracted RTCM message ID: {message_id}")
        return message_id

    @staticmethod
    def extract_message_length(data: bytes) -> int | None:
        """Extract RTCM message payload length from frame.

        Args:
            data: Raw RTCM message bytes

        Returns:
            Payload length in bytes if valid RTCM v3 frame, None otherwise
        """
        if len(data) < 3:
            return None

        if data[0] != 0xD3:
            return None

        # Extract length (10 bits)
        length = ((data[1] & 0x03) << 8) | data[2]
        return length

    @staticmethod
    def extract_all_message_ids(data: bytes) -> list[int]:
        """Extract all RTCM message IDs from a data buffer.

        Parses through the entire buffer to find and extract all RTCM messages.
        This handles cases where multiple RTCM messages are concatenated together.

        Args:
            data: Raw data buffer potentially containing multiple RTCM messages

        Returns:
            List of message IDs found in the buffer (may be empty)

        Examples:
            >>> # Buffer with two messages: 1005 and 1077
            >>> data = b'\\xd3\\x00\\x13\\x3e\\xd0...' + b'\\xd3\\x00\\x20\\x43\\x50...'
            >>> RTCMMessageDecoder.extract_all_message_ids(data)
            [1005, 1077]
        """
        message_ids: list[int] = []
        offset = 0

        while offset < len(data):
            # Look for RTCM preamble
            if data[offset] != 0xD3:
                offset += 1
                continue

            # Need at least 8 bytes for valid frame
            remaining = len(data) - offset
            if remaining < 8:
                break

            # Extract message length
            length = ((data[offset + 1] & 0x03) << 8) | data[offset + 2]
            expected_frame_length = 3 + length + 3

            # Check if complete frame is available
            if remaining < expected_frame_length:
                break

            # Extract frame
            frame = data[offset : offset + expected_frame_length]

            # Extract message ID from this frame
            msg_id = RTCMMessageDecoder.extract_message_id(frame)
            if msg_id is not None:
                message_ids.append(msg_id)
                logger.debug(f"Found RTCM message ID {msg_id} at offset {offset}")

            # Move to next potential message
            offset += expected_frame_length

        return message_ids

    @staticmethod
    def is_valid_rtcm_frame(data: bytes) -> bool:
        """Check if data appears to be a valid RTCM v3 frame.

        Performs basic validation without full CRC check.

        Args:
            data: Raw message bytes

        Returns:
            True if data looks like valid RTCM v3 frame
        """
        # Check minimum length
        if len(data) < 8:
            return False

        # Check preamble
        if data[0] != 0xD3:
            return False

        # Extract and validate length
        length = ((data[1] & 0x03) << 8) | data[2]
        expected_frame_length = 3 + length + 3

        # Check frame length matches
        if len(data) < expected_frame_length:
            return False

        return True
