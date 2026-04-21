"""RTCM message decoder for extracting message IDs and metadata.

This module provides utilities for parsing RTCM v3 messages to extract
message IDs for metrics tracking. The decoder is designed for minimal
overhead and is used for post-send metrics collection only.

Implements CRC-24Q validation as per RTCM v3 standard to ensure only
valid RTCM frames are processed.
"""

import logging


logger = logging.getLogger(__name__)


# CRC-24Q lookup table for RTCM v3 validation
# Polynomial: 0x1864CFB (x^24 + x^23 + x^18 + x^17 + x^14 + x^11 + x^10 + x^7 + x^6 + x^5 + x^4 + x^3 + x + 1)
# Used by RTCM 10403.x, Qualcomm, and PGP 6.5.1
CRC24Q_TABLE = [
    0x000000, 0x864CFB, 0x8AD50D, 0x0C99F6, 0x93E6E1, 0x15AA1A, 0x1933EC, 0x9F7F17,
    0xA18139, 0x27CDC2, 0x2B5434, 0xAD18CF, 0x3267D8, 0xB42B23, 0xB8B2D5, 0x3EFE2E,
    0xC54E89, 0x430272, 0x4F9B84, 0xC9D77F, 0x56A868, 0xD0E493, 0xDC7D65, 0x5A319E,
    0x64CFB0, 0xE2834B, 0xEE1ABD, 0x685646, 0xF72951, 0x7165AA, 0x7DFC5C, 0xFBB0A7,
    0x0CD1E9, 0x8A9D12, 0x8604E4, 0x00481F, 0x9F3708, 0x197BF3, 0x15E205, 0x93AEFE,
    0xAD50D0, 0x2B1C2B, 0x2785DD, 0xA1C926, 0x3EB631, 0xB8FACA, 0xB4633C, 0x322FC7,
    0xC99F60, 0x4FD39B, 0x434A6D, 0xC50696, 0x5A7981, 0xDC357A, 0xD0AC8C, 0x56E077,
    0x681E59, 0xEE52A2, 0xE2CB54, 0x6487AF, 0xFBF8B8, 0x7DB443, 0x712DB5, 0xF7614E,
    0x19A3D2, 0x9FEF29, 0x9376DF, 0x153A24, 0x8A4533, 0x0C09C8, 0x00903E, 0x86DCC5,
    0xB822EB, 0x3E6E10, 0x32F7E6, 0xB4BB1D, 0x2BC40A, 0xAD88F1, 0xA11107, 0x275DFC,
    0xDCED5B, 0x5AA1A0, 0x563856, 0xD074AD, 0x4F0BBA, 0xC94741, 0xC5DEB7, 0x43924C,
    0x7D6C62, 0xFB2099, 0xF7B96F, 0x71F594, 0xEE8A83, 0x68C678, 0x645F8E, 0xE21375,
    0x15723B, 0x933EC0, 0x9FA736, 0x19EBCD, 0x8694DA, 0x00D821, 0x0C41D7, 0x8A0D2C,
    0xB4F302, 0x32BFF9, 0x3E260F, 0xB86AF4, 0x2715E3, 0xA15918, 0xADC0EE, 0x2B8C15,
    0xD03CB2, 0x567049, 0x5AE9BF, 0xDCA544, 0x43DA53, 0xC596A8, 0xC90F5E, 0x4F43A5,
    0x71BD8B, 0xF7F170, 0xFB6886, 0x7D247D, 0xE25B6A, 0x641791, 0x688E67, 0xEEC29C,
    0x3347A4, 0xB50B5F, 0xB992A9, 0x3FDE52, 0xA0A145, 0x26EDBE, 0x2A7448, 0xAC38B3,
    0x92C69D, 0x148A66, 0x181390, 0x9E5F6B, 0x01207C, 0x876C87, 0x8BF571, 0x0DB98A,
    0xF6092D, 0x7045D6, 0x7CDC20, 0xFA90DB, 0x65EFCC, 0xE3A337, 0xEF3AC1, 0x69763A,
    0x578814, 0xD1C4EF, 0xDD5D19, 0x5B11E2, 0xC46EF5, 0x42220E, 0x4EBBF8, 0xC8F703,
    0x3F964D, 0xB9DAB6, 0xB54340, 0x330FBB, 0xAC70AC, 0x2A3C57, 0x26A5A1, 0xA0E95A,
    0x9E1774, 0x185B8F, 0x14C279, 0x928E82, 0x0DF195, 0x8BBD6E, 0x872498, 0x016863,
    0xFAD8C4, 0x7C943F, 0x700DC9, 0xF64132, 0x693E25, 0xEF72DE, 0xE3EB28, 0x65A7D3,
    0x5B59FD, 0xDD1506, 0xD18CF0, 0x57C00B, 0xC8BF1C, 0x4EF3E7, 0x426A11, 0xC426EA,
    0x2AE476, 0xACA88D, 0xA0317B, 0x267D80, 0xB90297, 0x3F4E6C, 0x33D79A, 0xB59B61,
    0x8B654F, 0x0D29B4, 0x01B042, 0x87FCB9, 0x1883AE, 0x9ECF55, 0x9256A3, 0x141A58,
    0xEFAAFF, 0x69E604, 0x657FF2, 0xE33309, 0x7C4C1E, 0xFA00E5, 0xF69913, 0x70D5E8,
    0x4E2BC6, 0xC8673D, 0xC4FECB, 0x42B230, 0xDDCD27, 0x5B81DC, 0x57182A, 0xD154D1,
    0x26359F, 0xA07964, 0xACE092, 0x2AAC69, 0xB5D37E, 0x339F85, 0x3F0673, 0xB94A88,
    0x87B4A6, 0x01F85D, 0x0D61AB, 0x8B2D50, 0x145247, 0x921EBC, 0x9E874A, 0x18CBB1,
    0xE37B16, 0x6537ED, 0x69AE1B, 0xEFE2E0, 0x709DF7, 0xF6D10C, 0xFA48FA, 0x7C0401,
    0x42FA2F, 0xC4B6D4, 0xC82F22, 0x4E63D9, 0xD11CCE, 0x575035, 0x5BC9C3, 0xDD8538,
]


class RTCMMessageDecoder:
    """Lightweight RTCM v3 message decoder for metrics collection.

    This decoder extracts message IDs from RTCM v3 frames with CRC-24Q
    validation to ensure only valid RTCM messages are counted.
    Designed for post-send metrics tracking with minimal performance impact.

    RTCM v3 Frame Format:
    - Byte 0: Preamble (0xD3)
    - Bytes 1-2: Reserved (6 bits) + Message Length (10 bits)
    - Bytes 3-4: Message ID (12 bits) + payload start
    - Payload: Variable length
    - CRC: 3 bytes (24 bits, CRC-24Q algorithm)
    """

    @staticmethod
    def calc_crc24q(data: bytes) -> int:
        """Calculate CRC-24Q checksum for RTCM v3 frame.

        Uses the CRC-24Q polynomial: 0x1864CFB
        (x^24 + x^23 + x^18 + x^17 + x^14 + x^11 + x^10 + x^7 + x^6 + x^5 + x^4 + x^3 + x + 1)

        Args:
            data: Raw bytes to calculate CRC over (typically frame without CRC bytes)

        Returns:
            24-bit CRC value

        Examples:
            >>> # Calculate CRC for RTCM frame (first N-3 bytes)
            >>> frame = b'\\xd3\\x00\\x13\\x3e\\xd0...'
            >>> crc = RTCMMessageDecoder.calc_crc24q(frame[:-3])
        """
        crc = 0
        for byte in data:
            crc = ((crc << 8) & 0xFFFFFF) ^ CRC24Q_TABLE[(crc >> 16) ^ byte]
        return crc

    @staticmethod
    def validate_crc24q(frame: bytes) -> bool:
        """Validate RTCM v3 frame using CRC-24Q checksum.

        The CRC is computed over all bytes except the last 3 (the CRC itself).
        The computed CRC must match the CRC stored in the last 3 bytes.

        Args:
            frame: Complete RTCM v3 frame including CRC bytes

        Returns:
            True if CRC is valid, False otherwise

        Examples:
            >>> frame = b'\\xd3\\x00\\x13\\x3e\\xd0...'  # Complete RTCM frame
            >>> RTCMMessageDecoder.validate_crc24q(frame)
            True
        """
        if len(frame) < 6:  # Minimum: 3 header + 3 CRC
            return False

        # CRC computed over all bytes except last 3 (the CRC itself)
        payload_length = len(frame) - 3
        computed_crc = RTCMMessageDecoder.calc_crc24q(frame[:payload_length])

        # Extract CRC from last 3 bytes (big-endian)
        frame_crc = (frame[-3] << 16) | (frame[-2] << 8) | frame[-1]

        return computed_crc == frame_crc

    @staticmethod
    def extract_message_id(data: bytes, validate_crc: bool = True) -> int | None:
        """Extract RTCM message ID from message data with CRC validation.

        Args:
            data: Raw RTCM message bytes
            validate_crc: If True, validate CRC-24Q checksum (default: True)

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

        # Validate length range (10-bit field max is 1023)
        if length > 1023:
            logger.debug(f"Invalid RTCM message length: {length}")
            return None

        # Validate frame completeness
        # RTCM v3 frame should be: 3 (header) + length (payload) + 3 (CRC)
        expected_frame_length = 3 + length + 3
        if len(data) < expected_frame_length:
            logger.debug(
                f"RTCM frame incomplete: got {len(data)} bytes, "
                f"expected {expected_frame_length}"
            )
            return None

        # Validate CRC-24Q checksum (critical for rejecting corrupted/spurious frames)
        if validate_crc:
            frame = data[:expected_frame_length]
            if not RTCMMessageDecoder.validate_crc24q(frame):
                logger.debug(
                    f"RTCM frame failed CRC-24Q validation "
                    f"(length={length}, frame_len={len(frame)})"
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

        logger.debug(f"Extracted RTCM message ID: {message_id} (CRC validated)")
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
    def is_valid_rtcm_frame(data: bytes, validate_crc: bool = True) -> bool:
        """Check if data is a valid RTCM v3 frame with CRC validation.

        Performs comprehensive validation including CRC-24Q checksum
        to ensure frame integrity.

        Args:
            data: Raw message bytes
            validate_crc: If True, validate CRC-24Q checksum (default: True)

        Returns:
            True if data is valid RTCM v3 frame, False otherwise
        """
        # Check minimum length
        if len(data) < 8:
            return False

        # Check preamble
        if data[0] != 0xD3:
            return False

        # Extract and validate length
        length = ((data[1] & 0x03) << 8) | data[2]
        
        # Validate length range (10-bit field max is 1023)
        if length > 1023:
            return False
            
        expected_frame_length = 3 + length + 3

        # Check frame length matches
        if len(data) < expected_frame_length:
            return False

        # Validate CRC-24Q checksum
        if validate_crc:
            frame = data[:expected_frame_length]
            if not RTCMMessageDecoder.validate_crc24q(frame):
                return False

        return True
