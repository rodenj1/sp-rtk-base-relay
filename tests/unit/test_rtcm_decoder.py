"""Unit tests for RTCM message decoder."""

from sp_base_relay.rtcm_decoder import RTCMMessageDecoder


class TestRTCMMessageDecoder:
    """Tests for RTCMMessageDecoder."""

    def test_extract_message_id_valid_rtcm_1005(self):
        """Test extracting message ID from valid RTCM 1005 message."""
        # RTCM 1005: Station coordinates
        # 0xD3 + length (0x0013 = 19 bytes) + message ID 1005 (0x3ED)
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005 (bits: 0011 1110 1101 0000)
            # Payload (17 bytes)
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 1005

    def test_extract_message_id_valid_rtcm_1077(self):
        """Test extracting message ID from valid RTCM 1077 message."""
        # RTCM 1077: GPS MSM7
        # Message ID 1077 (0x435)
        data = bytes([
            0xD3, 0x00, 0x20,  # Preamble + length (32 bytes)
            0x43, 0x50,        # Message ID 1077 (bits: 0100 0011 0101 0000)
            # Payload (30 bytes)
            *([0x00] * 30),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 1077

    def test_extract_message_id_valid_rtcm_1087(self):
        """Test extracting message ID from valid RTCM 1087 message."""
        # RTCM 1087: GLONASS MSM7
        # Message ID 1087 (0x43F)
        data = bytes([
            0xD3, 0x00, 0x25,  # Preamble + length (37 bytes)
            0x43, 0xF0,        # Message ID 1087 (bits: 0100 0011 1111 0000)
            # Payload (35 bytes)
            *([0x00] * 35),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 1087

    def test_extract_message_id_valid_rtcm_1230(self):
        """Test extracting message ID from valid RTCM 1230 message."""
        # RTCM 1230: GLONASS code-phase biases
        # Message ID 1230 (0x4CE)
        data = bytes([
            0xD3, 0x00, 0x1B,  # Preamble + length (27 bytes)
            0x4C, 0xE0,        # Message ID 1230 (bits: 0100 1100 1110 0000)
            # Payload (25 bytes)
            *([0x00] * 25),
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 1230

    def test_extract_message_id_minimum_valid_message(self):
        """Test extracting message ID from minimum valid RTCM frame."""
        # Minimum frame: 8 bytes total (3 header + 2 ID + 3 CRC)
        # Length field = 0 (no payload beyond message ID)
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length (2 bytes - just message ID)
            0x00, 0x10,        # Message ID 1 (bits: 0000 0000 0001 0000)
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 1

    def test_extract_message_id_maximum_id_value(self):
        """Test extracting maximum 12-bit message ID (4095)."""
        # Maximum message ID: 4095 (0xFFF)
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0xFF, 0xF0,        # Message ID 4095 (bits: 1111 1111 1111 0000)
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
        assert message_id == 4095

    def test_extract_message_id_zero(self):
        """Test extracting message ID 0."""
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0x00, 0x00,        # Message ID 0
            # CRC (3 bytes)
            0x00, 0x00, 0x00
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
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
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 17),    # Payload
            0x00, 0x00, 0x00,  # CRC
            # Extra bytes (should be ignored)
            0xFF, 0xFF, 0xFF
        ])

        message_id = RTCMMessageDecoder.extract_message_id(data)
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
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID
            *([0x00] * 17),    # Payload
            0x00, 0x00, 0x00   # CRC
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is True

    def test_is_valid_rtcm_frame_minimum(self):
        """Test is_valid_rtcm_frame with minimum valid frame."""
        data = bytes([
            0xD3, 0x00, 0x02,  # Preamble + length
            0x00, 0x10,        # Message ID
            0x00, 0x00, 0x00   # CRC
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is True

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
        data = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00,
            0xFF, 0xFF  # Extra bytes
        ])

        assert RTCMMessageDecoder.is_valid_rtcm_frame(data) is True

    def test_extract_message_id_common_messages(self):
        """Test extracting IDs from commonly used RTCM messages."""
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

            message_id = RTCMMessageDecoder.extract_message_id(data)
            assert message_id == expected_id, f"Failed for message ID {expected_id}"

    def test_extract_all_message_ids_single_message(self):
        """Test extracting all IDs from buffer with single message."""
        # Single message 1005
        data = bytes([
            0xD3, 0x00, 0x13,  # Preamble + length
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 17),    # Payload
            0x00, 0x00, 0x00   # CRC
        ])

        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005]

    def test_extract_all_message_ids_two_messages(self):
        """Test extracting all IDs from buffer with two messages."""
        # Message 1005 (19 bytes payload)
        msg1 = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00
        ])

        # Message 1077 (32 bytes payload)
        msg2 = bytes([
            0xD3, 0x00, 0x20,
            0x43, 0x50,
            *([0x00] * 30),
            0x00, 0x00, 0x00
        ])

        data = msg1 + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == [1005, 1077]

    def test_extract_all_message_ids_three_messages(self):
        """Test extracting all IDs from buffer with three messages."""
        # Message 1005
        msg1 = bytes([0xD3, 0x00, 0x02, 0x3E, 0xD0, 0x00, 0x00, 0x00])

        # Message 1077
        msg2 = bytes([0xD3, 0x00, 0x02, 0x43, 0x50, 0x00, 0x00, 0x00])

        # Message 1087
        msg3 = bytes([0xD3, 0x00, 0x02, 0x43, 0xF0, 0x00, 0x00, 0x00])

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
        # Complete message 1005
        msg1 = bytes([
            0xD3, 0x00, 0x13,
            0x3E, 0xD0,
            *([0x00] * 17),
            0x00, 0x00, 0x00
        ])

        # Incomplete message (only header, no payload/CRC)
        incomplete = bytes([0xD3, 0x00, 0x20, 0x43, 0x50])

        data = msg1 + incomplete
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should only get the complete message
        assert message_ids == [1005]

    def test_extract_all_message_ids_with_junk_data(self):
        """Test extracting all IDs with junk data between messages."""
        # Message 1005
        msg1 = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            0x00, 0x00, 0x00
        ])

        # Junk data (no valid preamble)
        junk = bytes([0xFF, 0xAA, 0xBB])

        # Message 1077
        msg2 = bytes([
            0xD3, 0x00, 0x02,
            0x43, 0x50,
            0x00, 0x00, 0x00
        ])

        data = msg1 + junk + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should find both valid messages, skipping junk
        assert message_ids == [1005, 1077]

    def test_extract_all_message_ids_invalid_message_skipped(self):
        """Test that invalid messages are skipped but valid ones are found."""
        # Valid message 1005
        msg1 = bytes([
            0xD3, 0x00, 0x02,
            0x3E, 0xD0,
            0x00, 0x00, 0x00
        ])

        # Invalid (wrong preamble)
        invalid = bytes([
            0xD4, 0x00, 0x02,
            0x43, 0x50,
            0x00, 0x00, 0x00
        ])

        # Valid message 1087
        msg2 = bytes([
            0xD3, 0x00, 0x02,
            0x43, 0xF0,
            0x00, 0x00, 0x00
        ])

        data = msg1 + invalid + msg2
        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        # Should find valid messages, skipping invalid
        assert message_ids == [1005, 1087]

    def test_extract_all_message_ids_large_payload(self):
        """Test extracting all IDs with messages having large payloads."""
        # Message with 500 byte payload
        msg1 = bytes([
            0xD3, 0x01, 0xF4,  # Preamble + length (500 = 0x01F4)
            0x3E, 0xD0,        # Message ID 1005
            *([0x00] * 498),   # Payload (498 + 2 ID bytes = 500)
            0x00, 0x00, 0x00   # CRC
        ])

        # Message with 100 byte payload
        msg2 = bytes([
            0xD3, 0x00, 0x64,  # Preamble + length (100 = 0x64)
            0x43, 0x50,        # Message ID 1077
            *([0x00] * 98),    # Payload (98 + 2 ID bytes = 100)
            0x00, 0x00, 0x00   # CRC
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
            # Build message
            msg = bytes([
                0xD3, (payload_size >> 8) & 0x03, payload_size & 0xFF,
                byte3, byte4,
                *([0x00] * (payload_size - 2)),  # -2 for ID bytes
                0x00, 0x00, 0x00  # CRC
            ])
            data += msg
            expected_ids.append(msg_id)

        message_ids = RTCMMessageDecoder.extract_all_message_ids(data)
        assert message_ids == expected_ids
