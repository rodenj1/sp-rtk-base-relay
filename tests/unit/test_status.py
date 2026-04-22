"""Tests for the Typed Status Snapshots (v2.1 Phase 2).

Covers:
- DestinationStatus frozen dataclass creation and immutability
- InputStatus frozen dataclass creation and immutability
- RelayStatus frozen dataclass creation and immutability
- build_destination_status() builder with mock destinations
- build_input_status() builder with mock input sources
- build_relay_status() builder with mock hub + input source
- Edge cases: not running, no destinations, no data received
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from sp_rtk_base_relay.core.destinations.base_destination import DestinationStats
from sp_rtk_base_relay.core.input_sources.base_input import InputSourceStats
from sp_rtk_base_relay.core.status import (
    DestinationStatus,
    InputStatus,
    RelayStatus,
    build_destination_status,
    build_input_status,
    build_relay_status,
)

# =========================================================================
# Helpers — mock factories
# =========================================================================


def _make_mock_destination(
    name: str = "test-dest",
    destination_type: str = "ntrip",
    enabled: bool = True,
    running: bool = True,
    connected: bool = True,
    filter_mode: str = "all",
    bytes_sent: int = 1000,
    messages_sent: int = 50,
    messages_dropped: int = 2,
    messages_filtered: int = 5,
    errors: int = 1,
    last_error: str | None = None,
    queue_depth: int = 3,
    connected_since: float | None = None,
    connection_attempts: int = 5,
    successful_connections: int = 4,
) -> MagicMock:
    """Create a mock BaseDestination with configurable stats."""
    if connected_since is None and connected:
        connected_since = time.time() - 60.0  # Connected 60s ago

    dest = MagicMock()
    dest.name = name
    dest.destination_type = destination_type
    dest.enabled = enabled
    dest.is_running = running
    dest.is_connected = connected
    dest.message_filter = MagicMock()
    dest.message_filter.mode = MagicMock()
    dest.message_filter.mode.value = filter_mode

    stats = DestinationStats(
        bytes_sent=bytes_sent,
        messages_sent=messages_sent,
        messages_dropped=messages_dropped,
        messages_filtered=messages_filtered,
        errors=errors,
        last_error=last_error,
        queue_depth=queue_depth,
        connected_since=connected_since,
        connection_attempts=connection_attempts,
        successful_connections=successful_connections,
    )
    dest.get_stats.return_value = stats
    return dest


def _make_mock_input_source(
    source_type: str = "serial",
    connected: bool = True,
    bytes_read: int = 5000,
    messages_read: int = 200,
    last_read_time: float = 0.0,
    connection_attempts: int = 3,
    successful_connections: int = 2,
    connected_since: float | None = None,
) -> MagicMock:
    """Create a mock InputSource with configurable stats."""
    if connected_since is None and connected:
        connected_since = time.time() - 120.0

    if last_read_time == 0.0 and connected:
        last_read_time = time.time() - 1.0

    src = MagicMock()
    src.source_type = source_type
    src.is_connected = connected

    stats = InputSourceStats(
        bytes_read=bytes_read,
        messages_read=messages_read,
        last_read_time=last_read_time,
        connection_attempts=connection_attempts,
        successful_connections=successful_connections,
        connected_since=connected_since,
    )
    src.stats = stats
    return src


def _make_mock_hub(
    running: bool = True,
    started_at: float | None = None,
    bytes_received: int = 10000,
    chunks_distributed: int = 500,
    frames_parsed: int = 300,
    no_data_warnings: int = 2,
    destinations: list[MagicMock] | None = None,
) -> MagicMock:
    """Create a mock BroadcastHub with configurable stats."""
    if started_at is None and running:
        started_at = time.time() - 300.0  # Started 5 min ago

    hub = MagicMock()
    hub.is_running = running
    hub.stats = MagicMock()
    hub.stats.started_at = started_at
    hub.stats.bytes_received = bytes_received
    hub.stats.chunks_distributed = chunks_distributed
    hub.stats.frames_parsed = frames_parsed
    hub.stats.no_data_warnings = no_data_warnings
    hub.destinations = destinations if destinations is not None else []
    return hub


# =========================================================================
# DestinationStatus Tests
# =========================================================================


class TestDestinationStatus:
    """Tests for the DestinationStatus frozen dataclass."""

    def test_create_destination_status(self) -> None:
        """Test creating a DestinationStatus with all fields."""
        status = DestinationStatus(
            name="rtk2go",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=True,
            filter_mode="all",
            bytes_sent=1000,
            messages_sent=50,
            messages_dropped=2,
            messages_filtered=5,
            errors=1,
            last_error=None,
            queue_depth=3,
            connected_since=1000.0,
            uptime_seconds=60.0,
            connection_attempts=5,
            successful_connections=4,
        )
        assert status.name == "rtk2go"
        assert status.destination_type == "ntrip"
        assert status.enabled is True
        assert status.running is True
        assert status.connected is True
        assert status.bytes_sent == 1000
        assert status.uptime_seconds == 60.0
        assert status.last_error is None

    def test_destination_status_is_frozen(self) -> None:
        """Test that DestinationStatus is immutable."""
        status = DestinationStatus(
            name="test",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=True,
            filter_mode="all",
            bytes_sent=0,
            messages_sent=0,
            messages_dropped=0,
            messages_filtered=0,
            errors=0,
            last_error=None,
            queue_depth=0,
            connected_since=None,
            uptime_seconds=None,
            connection_attempts=0,
            successful_connections=0,
        )
        with pytest.raises(AttributeError):
            status.name = "modified"  # type: ignore[misc]

    def test_destination_status_with_error(self) -> None:
        """Test DestinationStatus with an error recorded."""
        status = DestinationStatus(
            name="broken",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=False,
            filter_mode="all",
            bytes_sent=100,
            messages_sent=5,
            messages_dropped=10,
            messages_filtered=0,
            errors=3,
            last_error="Connection refused",
            queue_depth=50,
            connected_since=None,
            uptime_seconds=None,
            connection_attempts=10,
            successful_connections=2,
        )
        assert status.connected is False
        assert status.last_error == "Connection refused"
        assert status.errors == 3

    def test_destination_status_equality(self) -> None:
        """Test equality of DestinationStatus instances."""
        s1 = DestinationStatus(
            name="test",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=True,
            filter_mode="all",
            bytes_sent=100,
            messages_sent=10,
            messages_dropped=0,
            messages_filtered=0,
            errors=0,
            last_error=None,
            queue_depth=0,
            connected_since=1000.0,
            uptime_seconds=10.0,
            connection_attempts=1,
            successful_connections=1,
        )
        s2 = DestinationStatus(
            name="test",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=True,
            filter_mode="all",
            bytes_sent=100,
            messages_sent=10,
            messages_dropped=0,
            messages_filtered=0,
            errors=0,
            last_error=None,
            queue_depth=0,
            connected_since=1000.0,
            uptime_seconds=10.0,
            connection_attempts=1,
            successful_connections=1,
        )
        assert s1 == s2


# =========================================================================
# InputStatus Tests
# =========================================================================


class TestInputStatus:
    """Tests for the InputStatus frozen dataclass."""

    def test_create_input_status(self) -> None:
        """Test creating an InputStatus with all fields."""
        status = InputStatus(
            connected=True,
            source_type="serial",
            bytes_received=5000,
            messages_received=200,
            seconds_since_last_data=1.5,
            reconnect_attempts=3,
            reconnect_successes=2,
            connected_since=1000.0,
        )
        assert status.connected is True
        assert status.source_type == "serial"
        assert status.bytes_received == 5000
        assert status.seconds_since_last_data == 1.5

    def test_input_status_is_frozen(self) -> None:
        """Test that InputStatus is immutable."""
        status = InputStatus(
            connected=True,
            source_type="tcp",
            bytes_received=0,
            messages_received=0,
            seconds_since_last_data=-1.0,
            reconnect_attempts=0,
            reconnect_successes=0,
            connected_since=None,
        )
        with pytest.raises(AttributeError):
            status.connected = False  # type: ignore[misc]

    def test_input_status_disconnected(self) -> None:
        """Test InputStatus for a disconnected input."""
        status = InputStatus(
            connected=False,
            source_type="serial",
            bytes_received=0,
            messages_received=0,
            seconds_since_last_data=-1.0,
            reconnect_attempts=5,
            reconnect_successes=0,
            connected_since=None,
        )
        assert status.connected is False
        assert status.seconds_since_last_data == -1.0
        assert status.connected_since is None

    def test_input_status_equality(self) -> None:
        """Test equality of InputStatus instances."""
        s1 = InputStatus(
            connected=True,
            source_type="tcp",
            bytes_received=100,
            messages_received=10,
            seconds_since_last_data=2.0,
            reconnect_attempts=1,
            reconnect_successes=1,
            connected_since=1000.0,
        )
        s2 = InputStatus(
            connected=True,
            source_type="tcp",
            bytes_received=100,
            messages_received=10,
            seconds_since_last_data=2.0,
            reconnect_attempts=1,
            reconnect_successes=1,
            connected_since=1000.0,
        )
        assert s1 == s2


# =========================================================================
# RelayStatus Tests
# =========================================================================


class TestRelayStatus:
    """Tests for the RelayStatus frozen dataclass."""

    def test_create_relay_status(self) -> None:
        """Test creating a RelayStatus with all fields."""
        input_s = InputStatus(
            connected=True,
            source_type="serial",
            bytes_received=5000,
            messages_received=200,
            seconds_since_last_data=1.0,
            reconnect_attempts=1,
            reconnect_successes=1,
            connected_since=1000.0,
        )
        dest_s = DestinationStatus(
            name="rtk2go",
            destination_type="ntrip",
            enabled=True,
            running=True,
            connected=True,
            filter_mode="all",
            bytes_sent=1000,
            messages_sent=50,
            messages_dropped=0,
            messages_filtered=0,
            errors=0,
            last_error=None,
            queue_depth=0,
            connected_since=1000.0,
            uptime_seconds=60.0,
            connection_attempts=1,
            successful_connections=1,
        )
        status = RelayStatus(
            running=True,
            uptime_seconds=300.0,
            input=input_s,
            destinations=[dest_s],
            active_destination_count=1,
            total_destination_count=1,
            bytes_received=10000,
            chunks_distributed=500,
            frames_parsed=300,
            no_data_warnings=0,
        )
        assert status.running is True
        assert status.uptime_seconds == 300.0
        assert status.input.connected is True
        assert len(status.destinations) == 1
        assert status.destinations[0].name == "rtk2go"
        assert status.active_destination_count == 1

    def test_relay_status_is_frozen(self) -> None:
        """Test that RelayStatus is immutable."""
        input_s = InputStatus(
            connected=True,
            source_type="serial",
            bytes_received=0,
            messages_received=0,
            seconds_since_last_data=-1.0,
            reconnect_attempts=0,
            reconnect_successes=0,
            connected_since=None,
        )
        status = RelayStatus(
            running=True,
            uptime_seconds=0.0,
            input=input_s,
            destinations=[],
            active_destination_count=0,
            total_destination_count=0,
            bytes_received=0,
            chunks_distributed=0,
            frames_parsed=0,
            no_data_warnings=0,
        )
        with pytest.raises(AttributeError):
            status.running = False  # type: ignore[misc]

    def test_relay_status_no_destinations(self) -> None:
        """Test RelayStatus with no destinations."""
        input_s = InputStatus(
            connected=True,
            source_type="tcp",
            bytes_received=0,
            messages_received=0,
            seconds_since_last_data=-1.0,
            reconnect_attempts=1,
            reconnect_successes=1,
            connected_since=1000.0,
        )
        status = RelayStatus(
            running=True,
            uptime_seconds=60.0,
            input=input_s,
            destinations=[],
            active_destination_count=0,
            total_destination_count=0,
            bytes_received=0,
            chunks_distributed=0,
            frames_parsed=0,
            no_data_warnings=0,
        )
        assert status.total_destination_count == 0
        assert status.active_destination_count == 0
        assert status.destinations == []


# =========================================================================
# build_destination_status() Tests
# =========================================================================


class TestBuildDestinationStatus:
    """Tests for the build_destination_status() builder function."""

    def test_build_from_connected_destination(self) -> None:
        """Test building status from a connected destination."""
        dest = _make_mock_destination(
            name="rtk2go",
            destination_type="ntrip",
            connected=True,
            bytes_sent=1500,
            messages_sent=75,
            errors=0,
        )
        status = build_destination_status(dest)

        assert status.name == "rtk2go"
        assert status.destination_type == "ntrip"
        assert status.connected is True
        assert status.bytes_sent == 1500
        assert status.messages_sent == 75
        assert status.uptime_seconds is not None
        assert status.uptime_seconds > 0

    def test_build_from_disconnected_destination(self) -> None:
        """Test building status from a disconnected destination."""
        dest = _make_mock_destination(
            name="offline",
            connected=False,
            connected_since=None,
        )
        status = build_destination_status(dest)

        assert status.connected is False
        assert status.uptime_seconds is None

    def test_build_preserves_stats(self) -> None:
        """Test that build preserves all stat values."""
        dest = _make_mock_destination(
            bytes_sent=999,
            messages_sent=88,
            messages_dropped=7,
            messages_filtered=3,
            errors=2,
            last_error="timeout",
            queue_depth=10,
            connection_attempts=15,
            successful_connections=12,
        )
        status = build_destination_status(dest)

        assert status.bytes_sent == 999
        assert status.messages_sent == 88
        assert status.messages_dropped == 7
        assert status.messages_filtered == 3
        assert status.errors == 2
        assert status.last_error == "timeout"
        assert status.queue_depth == 10
        assert status.connection_attempts == 15
        assert status.successful_connections == 12

    def test_build_result_is_frozen(self) -> None:
        """Test that built status is immutable."""
        dest = _make_mock_destination()
        status = build_destination_status(dest)
        with pytest.raises(AttributeError):
            status.name = "changed"  # type: ignore[misc]

    def test_build_disabled_destination(self) -> None:
        """Test building status from a disabled destination."""
        dest = _make_mock_destination(enabled=False, running=False)
        status = build_destination_status(dest)
        assert status.enabled is False
        assert status.running is False

    def test_build_connected_since_tracking(self) -> None:
        """Test uptime calculation when connected_since is set."""
        connected_time = time.time() - 30.0
        dest = _make_mock_destination(
            connected=True,
            connected_since=connected_time,
        )
        status = build_destination_status(dest)
        assert status.connected_since == connected_time
        assert status.uptime_seconds is not None
        assert 29.0 <= status.uptime_seconds <= 32.0


# =========================================================================
# build_input_status() Tests
# =========================================================================


class TestBuildInputStatus:
    """Tests for the build_input_status() builder function."""

    def test_build_from_connected_input(self) -> None:
        """Test building status from a connected input source."""
        src = _make_mock_input_source(
            source_type="serial",
            connected=True,
            bytes_read=5000,
            messages_read=200,
        )
        status = build_input_status(src)

        assert status.connected is True
        assert status.source_type == "serial"
        assert status.bytes_received == 5000
        assert status.messages_received == 200
        assert status.seconds_since_last_data > 0

    def test_build_from_disconnected_input(self) -> None:
        """Test building status from a disconnected input source."""
        src = _make_mock_input_source(
            connected=False,
            bytes_read=0,
            messages_read=0,
            last_read_time=0.0,
            connected_since=None,
        )
        status = build_input_status(src)

        assert status.connected is False
        assert status.seconds_since_last_data == -1.0
        assert status.connected_since is None

    def test_build_no_data_received_yet(self) -> None:
        """Test building status when no data has been received yet."""
        src = MagicMock()
        src.source_type = "serial"
        src.is_connected = True
        src.stats = InputSourceStats(
            bytes_read=0,
            messages_read=0,
            last_read_time=0.0,
            connection_attempts=1,
            successful_connections=1,
            connected_since=time.time(),
        )
        status = build_input_status(src)
        assert status.seconds_since_last_data == -1.0

    def test_build_result_is_frozen(self) -> None:
        """Test that built status is immutable."""
        src = _make_mock_input_source()
        status = build_input_status(src)
        with pytest.raises(AttributeError):
            status.connected = False  # type: ignore[misc]

    def test_build_preserves_reconnect_stats(self) -> None:
        """Test that reconnect stats are preserved."""
        src = _make_mock_input_source(
            connection_attempts=10,
            successful_connections=8,
        )
        status = build_input_status(src)
        assert status.reconnect_attempts == 10
        assert status.reconnect_successes == 8

    def test_build_recent_data(self) -> None:
        """Test seconds_since_last_data with recent data."""
        src = _make_mock_input_source(
            last_read_time=time.time() - 2.0,
        )
        status = build_input_status(src)
        assert 1.0 <= status.seconds_since_last_data <= 4.0


# =========================================================================
# build_relay_status() Tests
# =========================================================================


class TestBuildRelayStatus:
    """Tests for the build_relay_status() builder function."""

    def test_build_running_hub_with_destinations(self) -> None:
        """Test building status from a running hub with destinations."""
        dest1 = _make_mock_destination(name="rtk2go", connected=True)
        dest2 = _make_mock_destination(name="onocoy", connected=True)
        hub = _make_mock_hub(
            running=True,
            destinations=[dest1, dest2],
            bytes_received=10000,
        )
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.running is True
        assert status.uptime_seconds is not None
        assert status.uptime_seconds > 0
        assert len(status.destinations) == 2
        assert status.destinations[0].name == "rtk2go"
        assert status.destinations[1].name == "onocoy"
        assert status.active_destination_count == 2
        assert status.total_destination_count == 2
        assert status.bytes_received == 10000

    def test_build_stopped_hub(self) -> None:
        """Test building status from a stopped hub."""
        hub = _make_mock_hub(running=False, started_at=None)
        src = _make_mock_input_source(connected=False, connected_since=None)

        status = build_relay_status(hub, src)

        assert status.running is False
        assert status.uptime_seconds is None

    def test_build_no_destinations(self) -> None:
        """Test building status with no destinations."""
        hub = _make_mock_hub(destinations=[])
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.destinations == []
        assert status.active_destination_count == 0
        assert status.total_destination_count == 0

    def test_build_mixed_destination_connectivity(self) -> None:
        """Test active_destination_count with mixed connectivity."""
        dest1 = _make_mock_destination(name="active", connected=True)
        dest2 = _make_mock_destination(name="offline", connected=False)
        dest3 = _make_mock_destination(name="active2", connected=True)
        hub = _make_mock_hub(destinations=[dest1, dest2, dest3])
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.total_destination_count == 3
        assert status.active_destination_count == 2

    def test_build_preserves_hub_stats(self) -> None:
        """Test that hub-level stats are preserved."""
        hub = _make_mock_hub(
            bytes_received=99999,
            chunks_distributed=5000,
            frames_parsed=3000,
            no_data_warnings=7,
        )
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.bytes_received == 99999
        assert status.chunks_distributed == 5000
        assert status.frames_parsed == 3000
        assert status.no_data_warnings == 7

    def test_build_result_is_frozen(self) -> None:
        """Test that built RelayStatus is immutable."""
        hub = _make_mock_hub()
        src = _make_mock_input_source()
        status = build_relay_status(hub, src)
        with pytest.raises(AttributeError):
            status.running = False  # type: ignore[misc]

    def test_build_uptime_calculation(self) -> None:
        """Test uptime calculation from hub started_at."""
        started_at = time.time() - 120.0
        hub = _make_mock_hub(running=True, started_at=started_at)
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.uptime_seconds is not None
        assert 119.0 <= status.uptime_seconds <= 122.0

    def test_build_uptime_none_when_stopped(self) -> None:
        """Test uptime is None when hub is stopped even if started_at exists."""
        hub = _make_mock_hub(
            running=False,
            started_at=time.time() - 100.0,
        )
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)
        assert status.uptime_seconds is None

    def test_build_input_status_included(self) -> None:
        """Test that input status is correctly included."""
        hub = _make_mock_hub()
        src = _make_mock_input_source(
            source_type="tcp",
            bytes_read=12345,
        )

        status = build_relay_status(hub, src)

        assert status.input.source_type == "tcp"
        assert status.input.bytes_received == 12345

    def test_build_all_destinations_disconnected(self) -> None:
        """Test status when all destinations are disconnected."""
        dest1 = _make_mock_destination(name="d1", connected=False)
        dest2 = _make_mock_destination(name="d2", connected=False)
        hub = _make_mock_hub(destinations=[dest1, dest2])
        src = _make_mock_input_source()

        status = build_relay_status(hub, src)

        assert status.active_destination_count == 0
        assert status.total_destination_count == 2
