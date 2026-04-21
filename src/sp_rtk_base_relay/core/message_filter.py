"""RTCM message filtering for per-destination data distribution.

This module provides message filtering capabilities for the v2.0
multi-destination broadcast architecture. Each destination can have
its own filter configuration to control which RTCM message types
are forwarded.

Filter modes (per DR-1):
- pass_all: No filtering, raw data forwarded with zero overhead
- allowlist: Only specified RTCM message type IDs pass through
- blocklist: All messages pass except specified IDs
"""

import logging
from dataclasses import dataclass
from enum import Enum


logger = logging.getLogger(__name__)


class FilterMode(Enum):
    """RTCM message filter operating mode.

    Defines how the message filter decides which RTCM messages
    to forward to a destination.
    """

    PASS_ALL = "pass_all"
    ALLOWLIST = "allowlist"
    BLOCKLIST = "blocklist"


@dataclass(frozen=True)
class FilterConfig:
    """Immutable configuration for a message filter.

    Attributes:
        mode: The filtering mode (pass_all, allowlist, or blocklist)
        message_ids: Set of RTCM message type IDs for allowlist/blocklist.
            Must be empty for pass_all mode.
    """

    mode: FilterMode
    message_ids: frozenset[int]

    def __post_init__(self) -> None:
        """Validate filter configuration after initialization."""
        if self.mode == FilterMode.PASS_ALL and self.message_ids:
            raise ValueError(
                "pass_all filter mode must have empty message_ids, "
                f"got {len(self.message_ids)} IDs"
            )
        if self.mode in (FilterMode.ALLOWLIST, FilterMode.BLOCKLIST) and not self.message_ids:
            raise ValueError(
                f"{self.mode.value} filter mode requires at least one message ID"
            )
        # Validate RTCM message ID range (12-bit field: 0-4095)
        for msg_id in self.message_ids:
            if not 0 <= msg_id <= 4095:
                raise ValueError(
                    f"Invalid RTCM message ID: {msg_id} "
                    "(must be 0-4095)"
                )

    @classmethod
    def pass_all(cls) -> "FilterConfig":
        """Create a pass_all filter configuration.

        Returns:
            FilterConfig with pass_all mode and empty message_ids
        """
        return cls(mode=FilterMode.PASS_ALL, message_ids=frozenset())

    @classmethod
    def allowlist(cls, message_ids: set[int] | frozenset[int] | list[int]) -> "FilterConfig":
        """Create an allowlist filter configuration.

        Args:
            message_ids: RTCM message type IDs to allow through

        Returns:
            FilterConfig with allowlist mode

        Raises:
            ValueError: If message_ids is empty or contains invalid IDs
        """
        return cls(mode=FilterMode.ALLOWLIST, message_ids=frozenset(message_ids))

    @classmethod
    def blocklist(cls, message_ids: set[int] | frozenset[int] | list[int]) -> "FilterConfig":
        """Create a blocklist filter configuration.

        Args:
            message_ids: RTCM message type IDs to block

        Returns:
            FilterConfig with blocklist mode

        Raises:
            ValueError: If message_ids is empty or contains invalid IDs
        """
        return cls(mode=FilterMode.BLOCKLIST, message_ids=frozenset(message_ids))


class MessageFilter:
    """Filters RTCM messages based on message type IDs.

    Used by the BroadcastHub to implement per-destination filtering
    as specified in design review decision DR-1.

    The filter operates on pre-parsed (message_id, frame_bytes) tuples,
    where frame parsing is done by the BroadcastHub using RTCMMessageDecoder.

    Examples:
        >>> # Pass-all filter (zero overhead path)
        >>> config = FilterConfig.pass_all()
        >>> f = MessageFilter(config)
        >>> f.requires_parsing  # False — BroadcastHub skips frame parsing
        False

        >>> # Allowlist filter
        >>> config = FilterConfig.allowlist({1005, 1077, 1087})
        >>> f = MessageFilter(config)
        >>> f.should_pass(1005)  # True
        True
        >>> f.should_pass(4072)  # False
        False
    """

    def __init__(self, config: FilterConfig) -> None:
        """Initialize message filter.

        Args:
            config: Immutable filter configuration
        """
        self._config = config
        logger.info(
            f"MessageFilter initialized: mode={config.mode.value}, "
            f"ids={sorted(config.message_ids) if config.message_ids else '(none)'}"
        )

    @property
    def config(self) -> FilterConfig:
        """Get the filter configuration."""
        return self._config

    @property
    def mode(self) -> FilterMode:
        """Get the filter mode."""
        return self._config.mode

    @property
    def requires_parsing(self) -> bool:
        """Check if this filter requires RTCM frame parsing.

        Returns:
            True if the filter uses allowlist or blocklist mode,
            meaning the BroadcastHub must parse RTCM frames to extract
            message IDs. False for pass_all mode (zero overhead).
        """
        return self._config.mode != FilterMode.PASS_ALL

    def should_pass(self, message_id: int) -> bool:
        """Check if a single RTCM message ID passes the filter.

        Args:
            message_id: RTCM message type ID (0-4095)

        Returns:
            True if the message should be forwarded to the destination
        """
        if self._config.mode == FilterMode.PASS_ALL:
            return True
        elif self._config.mode == FilterMode.ALLOWLIST:
            return message_id in self._config.message_ids
        else:  # BLOCKLIST
            return message_id not in self._config.message_ids

    def filter_frames(
        self, frames: list[tuple[int, bytes]]
    ) -> list[bytes]:
        """Filter a list of parsed RTCM frames.

        Takes pre-parsed frames (message_id, frame_bytes) and returns
        only the frame bytes that pass the filter.

        Args:
            frames: List of (message_id, raw_frame_bytes) tuples,
                as produced by BroadcastHub frame parsing

        Returns:
            List of raw frame bytes that passed the filter.
            For pass_all mode, returns all frame bytes unchanged.
        """
        if self._config.mode == FilterMode.PASS_ALL:
            return [frame_bytes for _, frame_bytes in frames]

        passed: list[bytes] = []
        filtered_count = 0

        for message_id, frame_bytes in frames:
            if self.should_pass(message_id):
                passed.append(frame_bytes)
            else:
                filtered_count += 1

        if filtered_count > 0:
            logger.debug(
                f"MessageFilter ({self._config.mode.value}): "
                f"passed {len(passed)}, filtered {filtered_count}"
            )

        return passed

    def __repr__(self) -> str:
        """Detailed string representation."""
        return (
            f"MessageFilter(mode={self._config.mode.value}, "
            f"ids={sorted(self._config.message_ids)})"
        )
