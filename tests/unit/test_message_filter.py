"""Tests for RTCM message filter module.

Tests cover FilterConfig, FilterMode, and MessageFilter with all three
filter modes: pass_all, allowlist, and blocklist.
"""

import pytest

from sp_rtk_base_relay.core.message_filter import (
    FilterConfig,
    FilterMode,
    MessageFilter,
)

# ============================================================================
# FilterMode Tests
# ============================================================================


class TestFilterMode:
    """Tests for FilterMode enum."""

    def test_pass_all_value(self) -> None:
        """pass_all mode has correct string value."""
        assert FilterMode.PASS_ALL.value == "pass_all"

    def test_allowlist_value(self) -> None:
        """allowlist mode has correct string value."""
        assert FilterMode.ALLOWLIST.value == "allowlist"

    def test_blocklist_value(self) -> None:
        """blocklist mode has correct string value."""
        assert FilterMode.BLOCKLIST.value == "blocklist"

    def test_from_string_pass_all(self) -> None:
        """FilterMode can be created from string value."""
        assert FilterMode("pass_all") == FilterMode.PASS_ALL

    def test_from_string_allowlist(self) -> None:
        """FilterMode can be created from allowlist string."""
        assert FilterMode("allowlist") == FilterMode.ALLOWLIST

    def test_from_string_blocklist(self) -> None:
        """FilterMode can be created from blocklist string."""
        assert FilterMode("blocklist") == FilterMode.BLOCKLIST

    def test_invalid_mode_raises(self) -> None:
        """Invalid mode string raises ValueError."""
        with pytest.raises(ValueError):
            FilterMode("invalid")

    def test_all_modes_enumerated(self) -> None:
        """All three modes are present."""
        modes = list(FilterMode)
        assert len(modes) == 3


# ============================================================================
# FilterConfig Tests
# ============================================================================


class TestFilterConfig:
    """Tests for FilterConfig dataclass."""

    # --- pass_all mode ---

    def test_pass_all_factory(self) -> None:
        """pass_all factory creates valid config."""
        config = FilterConfig.pass_all()
        assert config.mode == FilterMode.PASS_ALL
        assert config.message_ids == frozenset()

    def test_pass_all_direct_construction(self) -> None:
        """pass_all can be constructed directly."""
        config = FilterConfig(mode=FilterMode.PASS_ALL, message_ids=frozenset())
        assert config.mode == FilterMode.PASS_ALL

    def test_pass_all_with_ids_raises(self) -> None:
        """pass_all with message_ids raises ValueError."""
        with pytest.raises(ValueError, match="pass_all filter mode must have empty"):
            FilterConfig(mode=FilterMode.PASS_ALL, message_ids=frozenset({1005}))

    # --- allowlist mode ---

    def test_allowlist_factory_with_set(self) -> None:
        """allowlist factory works with set input."""
        config = FilterConfig.allowlist({1005, 1077, 1087})
        assert config.mode == FilterMode.ALLOWLIST
        assert config.message_ids == frozenset({1005, 1077, 1087})

    def test_allowlist_factory_with_list(self) -> None:
        """allowlist factory works with list input."""
        config = FilterConfig.allowlist([1005, 1077])
        assert config.mode == FilterMode.ALLOWLIST
        assert 1005 in config.message_ids
        assert 1077 in config.message_ids

    def test_allowlist_factory_with_frozenset(self) -> None:
        """allowlist factory works with frozenset input."""
        ids = frozenset({1005, 1077})
        config = FilterConfig.allowlist(ids)
        assert config.message_ids == ids

    def test_allowlist_empty_raises(self) -> None:
        """allowlist with empty message_ids raises ValueError."""
        with pytest.raises(ValueError, match="allowlist filter mode requires"):
            FilterConfig.allowlist([])

    def test_allowlist_empty_set_raises(self) -> None:
        """allowlist with empty set raises ValueError."""
        with pytest.raises(ValueError, match="allowlist filter mode requires"):
            FilterConfig.allowlist(set())

    # --- blocklist mode ---

    def test_blocklist_factory_with_set(self) -> None:
        """blocklist factory works with set input."""
        config = FilterConfig.blocklist({4072})
        assert config.mode == FilterMode.BLOCKLIST
        assert config.message_ids == frozenset({4072})

    def test_blocklist_factory_with_list(self) -> None:
        """blocklist factory works with list input."""
        config = FilterConfig.blocklist([4072, 1230])
        assert config.mode == FilterMode.BLOCKLIST
        assert 4072 in config.message_ids
        assert 1230 in config.message_ids

    def test_blocklist_empty_raises(self) -> None:
        """blocklist with empty message_ids raises ValueError."""
        with pytest.raises(ValueError, match="blocklist filter mode requires"):
            FilterConfig.blocklist([])

    # --- Message ID validation ---

    def test_valid_message_id_zero(self) -> None:
        """Message ID 0 is valid (minimum RTCM ID)."""
        config = FilterConfig.allowlist({0})
        assert 0 in config.message_ids

    def test_valid_message_id_4095(self) -> None:
        """Message ID 4095 is valid (maximum 12-bit RTCM ID)."""
        config = FilterConfig.allowlist({4095})
        assert 4095 in config.message_ids

    def test_invalid_message_id_negative(self) -> None:
        """Negative message ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid RTCM message ID"):
            FilterConfig.allowlist({-1})

    def test_invalid_message_id_too_large(self) -> None:
        """Message ID > 4095 raises ValueError."""
        with pytest.raises(ValueError, match="Invalid RTCM message ID"):
            FilterConfig.allowlist({4096})

    def test_invalid_message_id_way_too_large(self) -> None:
        """Very large message ID raises ValueError."""
        with pytest.raises(ValueError, match="Invalid RTCM message ID"):
            FilterConfig.blocklist({99999})

    # --- Immutability ---

    def test_frozen_dataclass(self) -> None:
        """FilterConfig is immutable (frozen dataclass)."""
        config = FilterConfig.pass_all()
        with pytest.raises(AttributeError):
            config.mode = FilterMode.ALLOWLIST  # type: ignore[misc]

    def test_message_ids_is_frozenset(self) -> None:
        """message_ids is a frozenset (immutable)."""
        config = FilterConfig.allowlist({1005, 1077})
        assert isinstance(config.message_ids, frozenset)

    # --- Common RTCM message type sets ---

    def test_typical_gps_allowlist(self) -> None:
        """Typical GPS+GLONASS+Galileo+BDS allowlist."""
        ids = {1005, 1077, 1087, 1097, 1127, 1230}
        config = FilterConfig.allowlist(ids)
        assert config.message_ids == frozenset(ids)
        assert len(config.message_ids) == 6

    def test_single_id_blocklist(self) -> None:
        """Single ID blocklist (common: block proprietary 4072)."""
        config = FilterConfig.blocklist({4072})
        assert len(config.message_ids) == 1


# ============================================================================
# MessageFilter Tests — pass_all mode
# ============================================================================


class TestMessageFilterPassAll:
    """Tests for MessageFilter in pass_all mode."""

    @pytest.fixture
    def filter(self) -> MessageFilter:
        """Create a pass_all filter."""
        return MessageFilter(FilterConfig.pass_all())

    def test_requires_parsing_false(self, filter: MessageFilter) -> None:
        """pass_all does NOT require RTCM frame parsing."""
        assert filter.requires_parsing is False

    def test_mode_is_pass_all(self, filter: MessageFilter) -> None:
        """Filter mode is PASS_ALL."""
        assert filter.mode == FilterMode.PASS_ALL

    def test_should_pass_any_id(self, filter: MessageFilter) -> None:
        """All message IDs pass through."""
        assert filter.should_pass(1005) is True
        assert filter.should_pass(1077) is True
        assert filter.should_pass(4072) is True
        assert filter.should_pass(0) is True
        assert filter.should_pass(4095) is True

    def test_filter_frames_returns_all(self, filter: MessageFilter) -> None:
        """filter_frames returns all frame bytes."""
        frames = [
            (1005, b"\xd3\x00\x13"),
            (1077, b"\xd3\x00\x20"),
            (4072, b"\xd3\x00\x30"),
        ]
        result = filter.filter_frames(frames)
        assert len(result) == 3
        assert result[0] == b"\xd3\x00\x13"
        assert result[1] == b"\xd3\x00\x20"
        assert result[2] == b"\xd3\x00\x30"

    def test_filter_frames_empty_list(self, filter: MessageFilter) -> None:
        """filter_frames handles empty list."""
        result = filter.filter_frames([])
        assert result == []

    def test_config_property(self, filter: MessageFilter) -> None:
        """config property returns the FilterConfig."""
        assert filter.config.mode == FilterMode.PASS_ALL

    def test_repr(self, filter: MessageFilter) -> None:
        """repr shows mode and empty ids."""
        r = repr(filter)
        assert "pass_all" in r
        assert "[]" in r


# ============================================================================
# MessageFilter Tests — allowlist mode
# ============================================================================


class TestMessageFilterAllowlist:
    """Tests for MessageFilter in allowlist mode."""

    @pytest.fixture
    def filter(self) -> MessageFilter:
        """Create an allowlist filter with common GPS messages."""
        return MessageFilter(
            FilterConfig.allowlist({1005, 1077, 1087, 1097, 1127, 1230})
        )

    def test_requires_parsing_true(self, filter: MessageFilter) -> None:
        """allowlist DOES require RTCM frame parsing."""
        assert filter.requires_parsing is True

    def test_mode_is_allowlist(self, filter: MessageFilter) -> None:
        """Filter mode is ALLOWLIST."""
        assert filter.mode == FilterMode.ALLOWLIST

    def test_should_pass_allowed_id(self, filter: MessageFilter) -> None:
        """Allowed message IDs pass through."""
        assert filter.should_pass(1005) is True
        assert filter.should_pass(1077) is True
        assert filter.should_pass(1087) is True
        assert filter.should_pass(1097) is True
        assert filter.should_pass(1127) is True
        assert filter.should_pass(1230) is True

    def test_should_block_unlisted_id(self, filter: MessageFilter) -> None:
        """Unlisted message IDs are blocked."""
        assert filter.should_pass(4072) is False
        assert filter.should_pass(1006) is False
        assert filter.should_pass(0) is False
        assert filter.should_pass(4095) is False

    def test_filter_frames_passes_allowed(self, filter: MessageFilter) -> None:
        """filter_frames only returns allowed frames."""
        frames = [
            (1005, b"frame_1005"),
            (4072, b"frame_4072"),
            (1077, b"frame_1077"),
            (1006, b"frame_1006"),
        ]
        result = filter.filter_frames(frames)
        assert len(result) == 2
        assert result[0] == b"frame_1005"
        assert result[1] == b"frame_1077"

    def test_filter_frames_all_blocked(self, filter: MessageFilter) -> None:
        """filter_frames returns empty when all blocked."""
        frames = [
            (4072, b"frame_4072"),
            (1006, b"frame_1006"),
        ]
        result = filter.filter_frames(frames)
        assert result == []

    def test_filter_frames_all_pass(self, filter: MessageFilter) -> None:
        """filter_frames returns all when all allowed."""
        frames = [
            (1005, b"frame_1005"),
            (1077, b"frame_1077"),
        ]
        result = filter.filter_frames(frames)
        assert len(result) == 2

    def test_single_id_allowlist(self) -> None:
        """Allowlist with single ID works."""
        f = MessageFilter(FilterConfig.allowlist({1005}))
        assert f.should_pass(1005) is True
        assert f.should_pass(1077) is False


# ============================================================================
# MessageFilter Tests — blocklist mode
# ============================================================================


class TestMessageFilterBlocklist:
    """Tests for MessageFilter in blocklist mode."""

    @pytest.fixture
    def filter(self) -> MessageFilter:
        """Create a blocklist filter blocking proprietary message 4072."""
        return MessageFilter(FilterConfig.blocklist({4072}))

    def test_requires_parsing_true(self, filter: MessageFilter) -> None:
        """blocklist DOES require RTCM frame parsing."""
        assert filter.requires_parsing is True

    def test_mode_is_blocklist(self, filter: MessageFilter) -> None:
        """Filter mode is BLOCKLIST."""
        assert filter.mode == FilterMode.BLOCKLIST

    def test_should_pass_non_blocked_id(self, filter: MessageFilter) -> None:
        """Non-blocked message IDs pass through."""
        assert filter.should_pass(1005) is True
        assert filter.should_pass(1077) is True
        assert filter.should_pass(0) is True
        assert filter.should_pass(4095) is True

    def test_should_block_blocked_id(self, filter: MessageFilter) -> None:
        """Blocked message IDs are blocked."""
        assert filter.should_pass(4072) is False

    def test_filter_frames_passes_non_blocked(self, filter: MessageFilter) -> None:
        """filter_frames passes non-blocked frames."""
        frames = [
            (1005, b"frame_1005"),
            (4072, b"frame_4072"),
            (1077, b"frame_1077"),
        ]
        result = filter.filter_frames(frames)
        assert len(result) == 2
        assert result[0] == b"frame_1005"
        assert result[1] == b"frame_1077"

    def test_filter_frames_all_blocked(self, filter: MessageFilter) -> None:
        """filter_frames returns empty when all blocked."""
        frames = [(4072, b"frame_4072")]
        result = filter.filter_frames(frames)
        assert result == []

    def test_multi_id_blocklist(self) -> None:
        """Blocklist with multiple IDs works."""
        f = MessageFilter(FilterConfig.blocklist({4072, 1230}))
        assert f.should_pass(4072) is False
        assert f.should_pass(1230) is False
        assert f.should_pass(1005) is True
        assert f.should_pass(1077) is True

    def test_repr(self, filter: MessageFilter) -> None:
        """repr shows mode and ids."""
        r = repr(filter)
        assert "blocklist" in r
        assert "4072" in r
