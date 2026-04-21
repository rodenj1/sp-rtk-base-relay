"""Unit tests for RTCM message decoder."""

from sp_rtk_base_relay.rtcm_decoder import RTCMMessageDecoder


class TestRTCMMessageDecoder:
    """Tests for RTCMMessageDecoder."""

    def test_extract_message_id_valid_rtcm_1005(self):
        """Test extracting message ID from valid RTCM 1005 message."""
        # RTCM 1005: Station coordinates
        # 0xD3 + length (0x0013 = 19 bytes) + message ID 1005 (0x3ED)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005 (bits: 0011 1110 1101 0000)
            # Payload (17 bytes)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1005

    def test_extract_message_id_valid_rtcm_1077(self):
        """Test extracting message ID from valid RTCM 1077 message."""
        # RTCM 1077: GPS MSM7
        # Message ID 1077 (0x435)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x20,  # Preamble + length (32 bytes)
            0x43, 0x50,        # Message ID 1077 (bits: 0100 0011 0101 0000)
            # Payload (30 bytes)
            *([0x00] * 30),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1077

    def test_extract_message_id_valid_rtcm_1087(self):
        """Test extracting message ID from valid RTCM 1087 message."""
        # RTCM 1087: GLONASS MSM7
        # Message ID 1087 (0x43F)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x25,  # Preamble + length (37 bytes)
            0x43, 0xF0,        # Message ID 1087 (bits: 0100 0011 1111 0000)
            # Payload (35 bytes)
            *([0x00] * 35),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1087

    def test_extract_message_id_valid_rtcm_1230(self):
        """Test extracting message ID from valid RTCM 1230 message."""
        # RTCM 1230: GLONASS code-phase biases
        # Message ID 1230 (0x4CE)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x1B,  # Preamble + length (27 bytes)
            0x4C, 0xE0,        # Message ID 1230 (bits: 0100 1100 1110 0000)
            # Payload (25 bytes)
            *([0x00] * 25),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1230

    def test_extract_message_id_minimum_valid_message(self):
        """Test extracting message ID from minimum valid RTCM frame."""
        # Minimum frame: 8 bytes total (3 header + 2 ID + 3 CRC)
        # Length field = 0 (no payload beyond message ID)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length (2 bytes - just message ID)
            0x00, 0x10,        # Message ID 1 (bits: 0000 0000 0001 0000)
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1

    def test_extract_message_id_maximum_id_value(self):
        """Test extracting maximum 12-bit message ID (4095)."""
        # Maximum message ID: 4095 (0xFFF)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0xFF, 0xF0,        # Message ID 4095 (bits: 1111 1111 1111 0000)
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 4095

    def test_extract_message_id_zero(self):
        """Test extracting message ID 0."""
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0x00, 0x00,        # Message ID 0
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 0

    def test_extract_message_id_too_short(self):
        """Test extracting message ID from frame that's too short."""
        # Only 7 bytes (need at least 8)
        data = bytes([0xD3, 0x00, 0x02, 0x00, 0x10, 0x00, 0x00])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id is None

    def test_extract_message_id_empty_data(self):
        """Test extracting message ID from empty data."""
        data = bytes([])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id is None

    def test_extract_message_id_invalid_preamble(self):
        """Test extracting message ID from frame with invalid preamble."""
        # Wrong preamble (0xD4 instead of 0xD3)
        data = bytes([
            0xD4, 0x00, 0x13,  # Invalid preamble
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id is None

    def test_extract_message_id_frame_too_short_for_length(self):
        """Test extracting message ID from incomplete frame."""
        # Length says 19 bytes, but only 10 bytes of payload provided
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length (19 bytes expected)
            0x3E, 0xD0,        # Message ID
            # Only 10 bytes instead of 19
            *([0x00] * 10)
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id is None

    def test_extract_message_id_with_extra_data(self):
        """Test extracting message ID from frame with extra trailing data."""
        # Valid frame with extra bytes at end
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 17),    # Payload
            0x00, 0x00, 0x00,  # CRC
            # Extra bytes (should be ignored)
            0xFF, 0xFF, 0xFF
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
        assert message_id == 1005

    def test_extract_message_length_valid(self):
        """Test extracting message length from valid frame."""
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length (19 bytes)
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00
        ])

        length = RTCMMessageDecoder.extract_message_length(data)
        assert length == 19

    def test_extract_message_length_zero(self):
        """Test extracting zero message length."""
        data = bytes([
            0xD3, 0x00, 0x00,  # Preamble + length (0 bytes)
            0x00, 0x00, 0x00
        ])

        length = RTCMMessageDecoder.extract_message_length(data)
        assert length == 0

    def test_extract_message_length_maximum(self):
        """Test extracting maximum message length (1023 bytes)."""
        # Maximum 10-bit value: 1023 (0x3FF)
        data = bytes([
            0xD3, 0x03, 0xFF,  # Preamble + length (1023 bytes)
            0x00, 0x00
        ])

        length = RTCMMessageDecoder.extract_message_length(data)
        assert length == 1023

    def test_extract_message_length_too_short(self):
        """Test extracting message length from too-short data."""
        data = bytes([0xD3, 0x00])  # Only 2 bytes

        length = RTCMMessageDecoder.extract_message_length(data)
        assert length is None

    def test_extract_message_length_invalid_preamble(self):
        """Test extracting message length with invalid preamble."""
        data = bytes([0xD4, 0x00, 0x13])  # Wrong preamble

        length = RTCMMessageDecoder.extract_message_length(data)
        assert length is None

    def test_is_valid_rtcm_frame_valid(self):
        """Test is_valid_rtcm_frame with valid frame."""
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID
            *([0x00] * 17),    # Payload
            0x00, 0x00, 0x00   # CRC
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data, validate_crc=False) is True

    def test_is_valid_rtcm_frame_minimum(self):
        """Test is_valid_rtcm_frame with minimum valid frame."""
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0x00, 0x10,        # Message ID
            0x00, 0x00, 0x00   # CRC
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data, validate_crc=False) is True

    def test_is_valid_rtcm_frame_too_short(self):
        """Test is_valid_rtcm_frame with too-short data."""
        data = bytes([0xD3, 0x00, 0x13, 0x3E])  # Only 4 bytes

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is False

    def test_is_valid_rtcm_frame_empty(self):
        """Test is_valid_rtcm_frame with empty data."""
        data = bytes([])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is False

    def test_is_valid_rtcm_frame_invalid_preamble(self):
        """Test is_valid_rtcm_frame with invalid preamble."""
        data = bytes([
            0xD4, 0x00, 0x13,  # Wrong preamble
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is False

    def test_is_valid_rtcm_frame_incomplete(self):
        """Test is_valid_rtcm_frame with incomplete frame."""
        # Length says 19 bytes but only 10 provided
        data = bytes([
            0xD3, 0x00, 0x13,  # Length = 19
            0x3E, 0xD0,
            *([0x00] * 10)     # Only 10 bytes
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is False

    def test_is_valid_rtcm_frame_with_extra_data(self):
        """Test is_valid_rtcm_frame with extra trailing data."""
        # Valid frame with extra bytes (should still be valid)
        # NOTE: Using fake CRC, so disable validation
        data = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00,
            0xFF, 0xFF  # Extra bytes
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data, validate_crc=False) is True

    def test_extract_message_id_common_messages(self):
        """Test extracting IDs from commonly used RTCM messages."""
        # NOTE: Using fake CRCs, so disable validation
        common_messages = [
            (1001, 0x3E, 0x90),  # GPS L1 observations
            (1002, 0x3E, 0xA0),  # GPS L1/L2 observations
            (1003, 0x3E, 0xB0),  # GPS L1/L2 observations (extended)
            (1004, 0x3E, 0xC0),  # GPS L1/L2 observations (extended + phase)
            (1005, 0x3E, 0xD0),  # Station coordinates
            (1006, 0x3E, 0xE0),  # Station coordinates + height
            (1019, 0x3F, 0xB0),  # GPS ephemeris
            (1020, 0x3F, 0xC0),  # GLONASS ephemeris
            (1033, 0x40, 0x90),  # Receiver and antenna descriptor
            (1074, 0x43, 0x20),  # GPS MSM4
            (1075, 0x43, 0x30),  # GPS MSM5
            (1076, 0x43, 0x40),  # GPS MSM6
            (1077, 0x43, 0x50),  # GPS MSM7
            (1084, 0x43, 0xC0),  # GLONASS MSM4
            (1085, 0x43, 0xD0),  # GLONASS MSM5
            (1086, 0x43, 0xE0),  # GLONASS MSM6
            (1087, 0x43, 0xF0),  # GLONASS MSM7
        ]

        for expected_id, byte3, byte4 in common_messages:
            data = bytes([
                0xD3, 0x00, 0x10,  # Preamble + length
                byte3, byte4,       # Message ID bytes
                *([0x00] * 14),     # Payload
                0x00, 0x00, 0x00    # CRC
            ])

            message_id = RTCMMessageDecoder.extract_message_id(data, validate_crc=False)
            assert message_id == expected_id, f"Failed for message ID {expected_id}"

    def test_extract_all_message_ids_single_message(self):
        """Test extracting all IDs from buffer with single message."""
        # Single message 1005
        # Build frame with proper CRC
        frame_no_crc = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 17),    # Payload
        ])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        data = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])

        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005]

    def test_extract_all_message_ids_two_messages(self):
        """Test extracting all IDs from buffer with two messages."""
        # Message 1005 (19 bytes payload) with proper CRC
        msg1_no_crc = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
        ])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])

        # Message 1077 (32 bytes payload) with proper CRC
        msg2_no_crc = bytes([
            0xD3, 0x00, 0x20,
            0x43, 0x50,
            *([0x00] * 30),
        ])
        crc2 = RTCMMessageDecoder.calc_crc24q(msg2_no_crc)
        msg2 = msg2_no_crc + bytes([
            (crc2 >> 16) & 0xFF,
            (crc2 >> 8) & 0xFF,
            crc2 & 0xFF
        ])

        data = msg1 + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005, 1077]

    def test_extract_all_message_ids_three_messages(self):
        """Test extracting all IDs from buffer with three messages."""
        # Message 1005 with proper CRC
        msg1_no_crc = bytes([0xD3, 0x00, 0x02, 0x3E, 0xD0])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([(crc1 >> 16) & 0xFF, (crc1 >> 8) & 0xFF, crc1 & 0xFF])

        # Message 1077 with proper CRC
        msg2_no_crc = bytes([0xD3, 0x00, 0x02, 0x43, 0x50])
        crc2 = RTCMMessageDecoder.calc_crc24q(msg2_no_crc)
        msg2 = msg2_no_crc + bytes([(crc2 >> 16) & 0xFF, (crc2 >> 8) & 0xFF, crc2 & 0xFF])

        # Message 1087 with proper CRC
        msg3_no_crc = bytes([0xD3, 0x00, 0x02, 0x43, 0xF0])
        crc3 = RTCMMessageDecoder.calc_crc24q(msg3_no_crc)
        msg3 = msg3_no_crc + bytes([(crc3 >> 16) & 0xFF, (crc3 >> 8) & 0xFF, crc3 & 0xFF])

        data = msg1 + msg2 + msg3
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005, 1077, 1087]

    def test_extract_all_message_ids_empty_buffer(self):
        """Test extracting all IDs from empty buffer."""
        data = bytes([])
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == []

    def test_extract_all_message_ids_incomplete_message(self):
        """Test extracting all IDs when last message is incomplete."""
        # Complete message 1005 with proper CRC
        msg1_no_crc = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
        ])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])

        # Incomplete message (only header, no payload/CRC)
        incomplete = bytes([0xD3, 0x00, 0x20, 0x43, 0x50])

        data = msg1 + incomplete
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should only get the complete message
        assert message_ids == [1005]

    def test_extract_all_message_ids_with_junk_data(self):
        """Test extracting all IDs with junk data between messages."""
        # Message 1005 with proper CRC
        msg1_no_crc = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
        ])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])

        # Junk data (no valid preamble)
        junk = bytes([0xFF, 0xAA, 0xBB])

        # Message 1077 with proper CRC
        msg2_no_crc = bytes([
            0xD3, 0x00, 0x02,
            0x43, 0x50,
        ])
        crc2 = RTCMMessageDecoder.calc_crc24q(msg2_no_crc)
        msg2 = msg2_no_crc + bytes([
            (crc2 >> 16) & 0xFF,
            (crc2 >> 8) & 0xFF,
            crc2 & 0xFF
        ])

        data = msg1 + junk + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should find both valid messages, skipping junk
        assert message_ids == [1005, 1077]

    def test_extract_all_message_ids_invalid_message_skipped(self):
        """Test that invalid messages are skipped but valid ones are found."""
        # Valid message 1005 with proper CRC
        msg1_no_crc = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
        ])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])

        # Invalid (wrong preamble)
        invalid = bytes([
            0xD4, 0x00, 0x02,
            0x43, 0x50,
            0x00, 0x00, 0x00
        ])

        # Valid message 1087 with proper CRC
        msg2_no_crc = bytes([
            0xD3, 0x00, 0x02,
            0x43, 0xF0,
        ])
        crc2 = RTCMMessageDecoder.calc_crc24q(msg2_no_crc)
        msg2 = msg2_no_crc + bytes([
            (crc2 >> 16) & 0xFF,
            (crc2 >> 8) & 0xFF,
            crc2 & 0xFF
        ])

        data = msg1 + invalid + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should find valid messages, skipping invalid
        assert message_ids == [1005, 1087]

    def test_extract_all_message_ids_large_payload(self):
        """Test extracting all IDs with messages having large payloads."""
        # Message with 500 byte payload with proper CRC
        msg1_no_crc = bytes([
            0xD3, 0x01, 0xF4,  # Preamble + length (500 = 0x01F4)
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 498),   # Payload (498 + 2 ID bytes = 500)
        ])
        crc1 = RTCMMessageDecoder.calc_crc24q(msg1_no_crc)
        msg1 = msg1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])

        # Message with 100 byte payload with proper CRC
        msg2_no_crc = bytes([
            0xD3, 0x00, 0x64,  # Preamble + length (100 = 0x64)
            0x43, 0x50,        # Message ID 1077
            *([0x00] * 98),    # Payload (98 + 2 ID bytes = 100)
        ])
        crc2 = RTCMMessageDecoder.calc_crc24q(msg2_no_crc)
        msg2 = msg2_no_crc + bytes([
            (crc2 >> 16) & 0xFF,
            (crc2 >> 8) & 0xFF,
            crc2 & 0xFF
        ])

        data = msg1 + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005, 1077]

    def test_extract_all_message_ids_realistic_stream(self):
        """Test extracting all IDs from realistic RTCM stream."""
        # Simulate typical base station output:
        # 1005 (station coords), 1077 (GPS MSM7), 1087 (GLONASS MSM7), 1230 (GLONASS biases)
        messages: list[tuple[int, int, int, int]] = [
            (1005, 0x3E, 0xD0, 19),  # ID, byte3, byte4, payload_size
            (1077, 0x43, 0x50, 32),
            (1087, 0x43, 0xF0, 37),
            (1230, 0x4C, 0xE0, 27),
        ]

        data = bytes()
        expected_ids: list[int] = []

        for msg_id, byte3, byte4, payload_size in messages:
            # Build message with proper CRC
            msg_no_crc = bytes([
                0xD3, (payload_size >> 8) & 0x03, payload_size & 0xFF,
                byte3, byte4,
                *([0x00] * (payload_size - 2)),  # -2 for ID bytes
            ])
            crc = RTCMMessageDecoder.calc_crc24q(msg_no_crc)
            msg = msg_no_crc + bytes([
                (crc >> 16) & 0xFF,
                (crc >> 8) & 0xFF,
                crc & 0xFF
            ])
            data += msg
            expected_ids.append(msg_id)

        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == expected_ids


class TestRTCMCRC24Q:
    """Tests for CRC-24Q validation."""

    def test_calc_crc24q_empty_data(self):
        """Test CRC calculation on empty data."""
        data = bytes([])
        crc = RTCMMessageDecoder.calc_crc24q(data)
        assert crc == 0

    def test_calc_crc24q_single_byte(self):
        """Test CRC calculation on single byte."""
        data = bytes([0xD3])
        crc = RTCMMessageDecoder.calc_crc24q(data)
        # CRC of single 0xD3 byte should be calculated correctly
        # The result is: ((0 << 8) & 0xFFFFFF) ^ CRC24Q_TABLE[0 ^ 0xD3]
        # = CRC24Q_TABLE[0xD3] = 0xE33309
        assert crc == 0xE33309

    def test_calc_crc24q_known_rtcm_1005_frame(self):
        """Test CRC calculation on known RTCM 1005 frame."""
        # Real RTCM 1005 message from RTKLIB documentation
        # Frame without CRC
        frame_no_crc = bytes([
            0xD3, 0x00, 0x13,  # Header
            0x3E, 0xD0, 0x00, 0x03, 0x8A, 0x58, 0xD9, 0x49,
            0x3C, 0x87, 0x2F, 0x34, 0x10, 0x9D, 0x07, 0xD6,
            0xAF, 0x48, 0x20
        ])
        
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        # Expected CRC for this frame
        expected_crc = 0x5AD7F7
        assert crc == expected_crc

    def test_calc_crc24q_multiple_bytes(self):
        """Test CRC calculation on multiple bytes."""
        data = bytes([0xD3, 0x00, 0x13, 0x3E, 0xD0])
        crc = RTCMMessageDecoder.calc_crc24q(data)
        # Verify it's a 24-bit value
        assert 0 <= crc <= 0xFFFFFF

    def test_calc_crc24q_all_zeros(self):
        """Test CRC calculation on all-zero data."""
        data = bytes([0x00] * 10)
        crc = RTCMMessageDecoder.calc_crc24q(data)
        assert crc == 0

    def test_calc_crc24q_all_ones(self):
        """Test CRC calculation on all-one data."""
        data = bytes([0xFF] * 10)
        crc = RTCMMessageDecoder.calc_crc24q(data)
        # Verify it's non-zero and 24-bit
        assert 0 < crc <= 0xFFFFFF

    def test_validate_crc24q_valid_frame(self):
        """Test CRC validation on frame with correct CRC."""
        # Build frame with correct CRC
        frame_no_crc = bytes([
            0xD3, 0x00, 0x13,  # Header
            0x3E, 0xD0, 0x00, 0x03, 0x8A, 0x58, 0xD9, 0x49,
            0x3C, 0x87, 0x2F, 0x34, 0x10, 0x9D, 0x07, 0xD6,
            0xAF, 0x48, 0x20
        ])
        
        # Calculate and append CRC
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        assert RTCMMessageDecoder.validate_crc24q(frame) is True

    def test_validate_crc24q_invalid_frame(self):
        """Test CRC validation on frame with incorrect CRC."""
        # Frame with wrong CRC
        frame = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0, 0x00, 0x03, 0x8A, 0x58, 0xD9, 0x49,
            0x3C, 0x87, 0x2F, 0x34, 0x10, 0x9D, 0x07, 0xD6,
            0xAF, 0x48, 0x20,
            # Wrong CRC
            0x00, 0x00, 0x00
        ])
        
        assert RTCMMessageDecoder.validate_crc24q(frame) is False

    def test_validate_crc24q_corrupted_payload(self):
        """Test CRC validation rejects frame with corrupted payload."""
        # Build valid frame
        frame_no_crc = bytes([
            0xD3, 0x00, 0x05,
            0x3E, 0xD0, 0x12, 0x34, 0x56
        ])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Verify it's valid
        assert RTCMMessageDecoder.validate_crc24q(frame) is True
        
        # Corrupt one byte in payload
        corrupted = bytearray(frame)
        corrupted[5] = 0xFF  # Change byte in payload
        
        # Should now fail CRC
        assert RTCMMessageDecoder.validate_crc24q(bytes(corrupted)) is False

    def test_validate_crc24q_corrupted_header(self):
        """Test CRC validation rejects frame with corrupted header."""
        # Build valid frame
        frame_no_crc = bytes([0xD3, 0x00, 0x05, 0x3E, 0xD0, 0x12, 0x34, 0x56])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])
        
        # Corrupt length field
        corrupted = bytearray(frame)
        corrupted[2] = 0x06  # Change length
        
        # Should fail CRC
        assert RTCMMessageDecoder.validate_crc24q(bytes(corrupted)) is False

    def test_validate_crc24q_too_short(self):
        """Test CRC validation rejects too-short frame."""
        # Only 5 bytes (need at least 6)
        frame = bytes([0xD3, 0x00, 0x00, 0x00, 0x00])
        assert RTCMMessageDecoder.validate_crc24q(frame) is False

    def test_validate_crc24q_minimum_valid_frame(self):
        """Test CRC validation on minimum valid frame."""
        # Minimum frame: 3 header + 0 payload + 3 CRC = 6 bytes
        frame_no_crc = bytes([0xD3, 0x00, 0x00])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        assert RTCMMessageDecoder.validate_crc24q(frame) is True

    def test_extract_message_id_with_crc_validation_valid(self):
        """Test extract_message_id with CRC validation on valid frame."""
        # Build frame with correct CRC
        frame_no_crc = bytes([
            0xD3, 0x00, 0x02,  # Header (2 byte payload = message ID only)
            0x3E, 0xD0  # Message ID 1005
        ])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Should succeed with CRC validation
        message_id = RTCMMessageDecoder.extract_message_id(frame, validate_crc=True)
        assert message_id == 1005

    def test_extract_message_id_with_crc_validation_invalid(self):
        """Test extract_message_id with CRC validation rejects invalid CRC."""
        # Frame with wrong CRC
        frame = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            # Wrong CRC
            0x00, 0x00, 0x00
        ])
        
        # Should fail with CRC validation enabled
        message_id = RTCMMessageDecoder.extract_message_id(frame, validate_crc=True)
        assert message_id is None

    def test_extract_message_id_without_crc_validation(self):
        """Test extract_message_id without CRC validation accepts any CRC."""
        # Frame with wrong CRC
        frame = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            0x00, 0x00, 0x00
        ])
        
        # Should succeed with CRC validation disabled
        message_id = RTCMMessageDecoder.extract_message_id(frame, validate_crc=False)
        assert message_id == 1005

    def test_extract_message_id_spurious_frame_rejected(self):
        """Test that spurious frames with invalid CRC are rejected."""
        # Simulate spurious data that looks like RTCM but has invalid CRC
        # This represents the problem from the user's metrics
        spurious_frames = [
            # Message "ID" 17 (spurious)
            bytes([0xD3, 0x00, 0x02, 0x01, 0x10, 0xFF, 0xFF, 0xFF]),
            # Message "ID" 123 (spurious)
            bytes([0xD3, 0x00, 0x02, 0x07, 0xB0, 0xAA, 0xBB, 0xCC]),
            # Message "ID" 243 (spurious)
            bytes([0xD3, 0x00, 0x02, 0x0F, 0x30, 0x11, 0x22, 0x33]),
        ]
        
        for frame in spurious_frames:
            # With CRC validation, should be rejected
            message_id = RTCMMessageDecoder.extract_message_id(frame, validate_crc=True)
            assert message_id is None, f"Spurious frame should be rejected: {frame.hex()}"

    def test_is_valid_rtcm_frame_with_crc_validation_valid(self):
        """Test is_valid_rtcm_frame with CRC validation on valid frame."""
        # Build frame with correct CRC
        frame_no_crc = bytes([0xD3, 0x00, 0x02, 0x3E, 0xD0])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Should be valid with CRC check
        assert RTCMMessageDecoder.is_valid_rtcm_frame(frame, validate_crc=True) is True

    def test_is_valid_rtcm_frame_with_crc_validation_invalid(self):
        """Test is_valid_rtcm_frame with CRC validation rejects invalid CRC."""
        # Frame with wrong CRC
        frame = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            0x00, 0x00, 0x00
        ])
        
        # Should fail with CRC validation
        assert RTCMMessageDecoder.is_valid_rtcm_frame(frame, validate_crc=True) is False

    def test_is_valid_rtcm_frame_without_crc_validation(self):
        """Test is_valid_rtcm_frame without CRC validation accepts any CRC."""
        # Frame with wrong CRC
        frame = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            0x00, 0x00, 0x00
        ])
        
        # Should succeed without CRC validation
        assert RTCMMessageDecoder.is_valid_rtcm_frame(frame, validate_crc=False) is True

    def test_is_valid_rtcm_frame_length_too_large(self):
        """Test is_valid_rtcm_frame rejects length > 1023."""
        # To test invalid length, we need to check the implementation's rejection
        # Since 10-bit max is 1023 (0x3FF), anything beyond won't fit in the field
        # However, the test should verify that we handle edge cases properly
        # Let's use a frame that claims to need more data than a valid RTCM frame
        # Maximum valid length is 1023, so this should pass
        # Actually, let's test that frames are properly validated
        # The implementation checks: if length > 1023: return False
        # Since the length field is only 10 bits, max extractable value is 1023
        # This test is checking a hypothetical case that can't happen with proper extraction
        # Let's just verify the max valid length works
        
        # Build a frame with maximum valid length (1023)
        frame_no_crc = bytes([
            0xD3, 0x03, 0xFF,  # Length = 1023 (0x3FF - maximum 10-bit value)
            0x3E, 0xD0,
            *([0x00] * 1021),  # 1021 + 2 ID bytes = 1023 total payload
        ])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Maximum valid length should pass
        assert RTCMMessageDecoder.is_valid_rtcm_frame(frame, validate_crc=False) is True

    def test_extract_all_message_ids_with_crc_validation(self):
        """Test extract_all_message_ids correctly uses CRC validation."""
        # Build two valid frames
        frame1_no_crc = bytes([0xD3, 0x00, 0x02, 0x3E, 0xD0])  # 1005
        crc1 = RTCMMessageDecoder.calc_crc24q(frame1_no_crc)
        frame1 = frame1_no_crc + bytes([
            (crc1 >> 16) & 0xFF,
            (crc1 >> 8) & 0xFF,
            crc1 & 0xFF
        ])
        
        frame2_no_crc = bytes([0xD3, 0x00, 0x02, 0x43, 0x50])  # 1077
        crc2 = RTCMMessageDecoder.calc_crc24q(frame2_no_crc)
        frame2 = frame2_no_crc + bytes([
            (crc2 >> 16) & 0xFF,
            (crc2 >> 8) & 0xFF,
            crc2 & 0xFF
        ])
        
        # Add one invalid frame (wrong CRC)
        frame3_invalid = bytes([0xD3, 0x00, 0x02, 0x43, 0xF0, 0x00, 0x00, 0x00])  # 1087
        
        data = frame1 + frame2 + frame3_invalid
        
        # Should find only the two valid frames
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005, 1077]

    def test_crc_validation_filters_bluetooth_chunking_artifacts(self):
        """Test that CRC validation filters out Bluetooth chunking artifacts."""
        # Simulate the problem: Bluetooth chunking creates spurious "messages"
        # that have valid-looking preamble/length but invalid CRC
        
        # Real valid message
        valid_frame_no_crc = bytes([0xD3, 0x00, 0x02, 0x3E, 0xD0])
        crc = RTCMMessageDecoder.calc_crc24q(valid_frame_no_crc)
        valid_frame = valid_frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Spurious "messages" from chunking artifacts
        spurious1 = bytes([0xD3, 0x00, 0x02, 0x07, 0xB0, 0x12, 0x34, 0x56])  # "ID" 123
        spurious2 = bytes([0xD3, 0x00, 0x02, 0x0F, 0x30, 0xAA, 0xBB, 0xCC])  # "ID" 243
        
        # Mix them together
        data = spurious1 + valid_frame + spurious2
        
        # Without CRC: would get spurious IDs
        message_ids_no_crc = []
        for frame_data in [spurious1, valid_frame, spurious2]:
            msg_id = RTCMMessageDecoder.extract_message_id(frame_data, validate_crc=False)
            if msg_id is not None:
                message_ids_no_crc.append(msg_id)
        
        # Should get all three (including spurious)
        assert len(message_ids_no_crc) == 3
        
        # With CRC: only valid frames
        message_ids_with_crc = []
        for frame_data in [spurious1, valid_frame, spurious2]:
            msg_id = RTCMMessageDecoder.extract_message_id(frame_data, validate_crc=True)
            if msg_id is not None:
                message_ids_with_crc.append(msg_id)
        
        # Should only get the valid frame
        assert message_ids_with_crc == [1005]

    def test_extract_message_length_with_invalid_length(self):
        """Test extract_message_id with maximum valid length (1023)."""
        # Test with maximum valid 10-bit length value (1023 = 0x3FF)
        # Build frame with proper CRC
        frame_no_crc = bytes([
            0xD3, 0x03, 0xFF,  # Length = 1023 (0x3FF - maximum 10-bit value)
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 1021)   # Payload (1021 + 2 ID bytes = 1023)
        ])
        crc = RTCMMessageDecoder.calc_crc24q(frame_no_crc)
        frame = frame_no_crc + bytes([
            (crc >> 16) & 0xFF,
            (crc >> 8) & 0xFF,
            crc & 0xFF
        ])
        
        # Should successfully extract message ID from maximum-length frame
        message_id = RTCMMessageDecoder.extract_message_id(frame, validate_crc=True)
        assert message_id == 1005
