"""Typed status snapshots for relay runtime introspection.

Provides frozen (immutable) dataclasses that capture a point-in-time
snapshot of the relay system state. These are safe to pass across
threads and serialize for API responses.

Components:
    - ``DestinationStatus``: Per-destination status snapshot.
    - ``InputStatus``: Input source status snapshot.
    - ``RelayStatus``: Top-level relay system status snapshot.
    - ``build_destination_status()``: Builder from a BaseDestination instance.
    - ``build_input_status()``: Builder from an InputSource instance.
    - ``build_relay_status()``: Builder from hub + input source.

Design decisions applied:
    - DR-10: Polling for current state — snapshot dataclasses returned by get_status()
    - All dataclasses are frozen for thread safety
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sp_base_relay.core.broadcast_hub import BroadcastHub
    from sp_base_relay.core.destinations.base_destination import BaseDestination
    from sp_base_relay.core.input_sources.base_input import InputSource


# ---------------------------------------------------------------------------
# DestinationStatus — per-destination snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DestinationStatus:
    """Frozen snapshot of a single destination's current state.

    All fields are read-only. Created by ``build_destination_status()``
    from a live ``BaseDestination`` instance.

    Attributes:
        name: Unique destination identifier.
        destination_type: Type string (surepath, ntrip, tcp_server).
        enabled: Whether the destination is enabled in config.
        running: Whether the destination thread is actively running.
        connected: Whether the destination has a live connection.
        filter_mode: Message filter mode (all, parsed, raw).
        bytes_sent: Total bytes sent to this destination.
        messages_sent: Total messages successfully sent.
        messages_dropped: Total messages dropped (queue full or disconnected).
        messages_filtered: Total messages filtered out by MessageFilter.
        errors: Total errors encountered.
        last_error: Most recent error message, or None.
        queue_depth: Current number of items waiting in the queue.
        connected_since: Epoch timestamp of last successful connection, or None.
        uptime_seconds: Seconds since last connection, or None if not connected.
        connection_attempts: Total connection attempts.
        successful_connections: Total successful connections.
    """

    name: str
    destination_type: str
    enabled: bool
    running: bool
    connected: bool
    filter_mode: str
    bytes_sent: int
    messages_sent: int
    messages_dropped: int
    messages_filtered: int
    errors: int
    last_error: str | None
    queue_depth: int
    connected_since: float | None
    uptime_seconds: float | None
    connection_attempts: int
    successful_connections: int


# ---------------------------------------------------------------------------
# InputStatus — input source snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputStatus:
    """Frozen snapshot of the input source's current state.

    Attributes:
        connected: Whether the input source is connected.
        source_type: Type string (serial, tcp, bluetooth).
        bytes_received: Total bytes read from the input source.
        messages_received: Total read operations that returned data.
        seconds_since_last_data: Seconds since last successful data read,
            or -1.0 if no data has been received yet.
        reconnect_attempts: Total connection attempts.
        reconnect_successes: Total successful connections.
        connected_since: Epoch timestamp of current connection, or None.
    """

    connected: bool
    source_type: str
    bytes_received: int
    messages_received: int
    seconds_since_last_data: float
    reconnect_attempts: int
    reconnect_successes: int
    connected_since: float | None


# ---------------------------------------------------------------------------
# RelayStatus — top-level system snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelayStatus:
    """Frozen snapshot of the entire relay system's current state.

    Provides a single object containing all relay state information,
    suitable for API responses, logging, or UI rendering.

    Attributes:
        running: Whether the relay hub is actively running.
        uptime_seconds: Seconds since the hub started, or None if not running.
        input: Input source status snapshot.
        destinations: List of per-destination status snapshots.
        active_destination_count: Number of destinations currently connected.
        total_destination_count: Total number of registered destinations.
        bytes_received: Total bytes received from input source (hub-level).
        chunks_distributed: Total data chunks distributed to destinations.
        frames_parsed: Total RTCM frames parsed.
        no_data_warnings: Number of no-data warning events.
    """

    running: bool
    uptime_seconds: float | None
    input: InputStatus
    destinations: list[DestinationStatus]
    active_destination_count: int
    total_destination_count: int
    bytes_received: int
    chunks_distributed: int
    frames_parsed: int
    no_data_warnings: int


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_destination_status(dest: BaseDestination) -> DestinationStatus:
    """Build a DestinationStatus snapshot from a live BaseDestination.

    Reads current stats and state from the destination and returns
    a frozen snapshot that is safe for cross-thread use.

    Args:
        dest: A live BaseDestination instance.

    Returns:
        Frozen DestinationStatus snapshot.
    """
    stats = dest.get_stats()
    now = time.time()

    uptime: float | None = None
    if stats.connected_since is not None and dest.is_connected:
        uptime = now - stats.connected_since

    return DestinationStatus(
        name=dest.name,
        destination_type=dest.destination_type,
        enabled=dest.enabled,
        running=dest.is_running,
        connected=dest.is_connected,
        filter_mode=dest.message_filter.mode.value,
        bytes_sent=stats.bytes_sent,
        messages_sent=stats.messages_sent,
        messages_dropped=stats.messages_dropped,
        messages_filtered=stats.messages_filtered,
        errors=stats.errors,
        last_error=stats.last_error,
        queue_depth=stats.queue_depth,
        connected_since=stats.connected_since,
        uptime_seconds=uptime,
        connection_attempts=stats.connection_attempts,
        successful_connections=stats.successful_connections,
    )


def build_input_status(input_source: InputSource) -> InputStatus:
    """Build an InputStatus snapshot from a live InputSource.

    Args:
        input_source: A live InputSource instance.

    Returns:
        Frozen InputStatus snapshot.
    """
    stats = input_source.stats
    now = time.time()

    if stats.last_read_time > 0:
        seconds_since_last = now - stats.last_read_time
    else:
        seconds_since_last = -1.0

    return InputStatus(
        connected=input_source.is_connected,
        source_type=input_source.source_type,
        bytes_received=stats.bytes_read,
        messages_received=stats.messages_read,
        seconds_since_last_data=seconds_since_last,
        reconnect_attempts=stats.connection_attempts,
        reconnect_successes=stats.successful_connections,
        connected_since=stats.connected_since,
    )


def build_relay_status(
    hub: BroadcastHub,
    input_source: InputSource,
) -> RelayStatus:
    """Build a RelayStatus snapshot from a live BroadcastHub and InputSource.

    Reads from ``hub.stats``, ``hub._destinations``, and ``input_source.stats``
    to produce a complete frozen snapshot of the relay system.

    Args:
        hub: A live BroadcastHub instance.
        input_source: A live InputSource instance.

    Returns:
        Frozen RelayStatus snapshot.
    """
    now = time.time()

    # Hub uptime
    uptime: float | None = None
    if hub.stats.started_at is not None and hub.is_running:
        uptime = now - hub.stats.started_at

    # Build input status
    input_status = build_input_status(input_source)

    # Build destination statuses
    dest_statuses: list[DestinationStatus] = []
    destinations = hub.destinations
    for dest in destinations:
        dest_statuses.append(build_destination_status(dest))

    active_count = sum(1 for d in dest_statuses if d.connected)

    return RelayStatus(
        running=hub.is_running,
        uptime_seconds=uptime,
        input=input_status,
        destinations=dest_statuses,
        active_destination_count=active_count,
        total_destination_count=len(dest_statuses),
        bytes_received=hub.stats.bytes_received,
        chunks_distributed=hub.stats.chunks_distributed,
        frames_parsed=hub.stats.frames_parsed,
        no_data_warnings=hub.stats.no_data_warnings,
    )
