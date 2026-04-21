"""Connection state management for RTCM server connections.

This module defines the connection states used throughout the RTCM client
to track the current status of the connection lifecycle.
"""

from enum import Enum


class ConnectionState(Enum):
    """RTCM server connection states.

    Represents the various states of the RTCM server connection lifecycle,
    from initial disconnection through authentication to active data streaming.
    """

    DISCONNECTED = "disconnected"
    """Not connected to the RTCM server."""

    CONNECTING = "connecting"
    """Attempting to establish TCP connection to RTCM server."""

    AUTHENTICATING = "authenticating"
    """TCP connection established, performing INIT authentication."""

    CONNECTED = "connected"
    """Successfully authenticated and ready for data streaming."""

    RECONNECTING = "reconnecting"
    """Connection lost, waiting before retry attempt."""

    ERROR = "error"
    """Connection failed due to error condition."""

    STOPPING = "stopping"
    """Gracefully shutting down connection."""

    def __str__(self) -> str:
        """Return human-readable state name."""
        return self.value

    @property
    def is_connected(self) -> bool:
        """Check if the connection is in a connected state."""
        return self == ConnectionState.CONNECTED

    @property
    def is_connecting(self) -> bool:
        """Check if the connection is in progress."""
        return self in (ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING)

    @property
    def can_send_data(self) -> bool:
        """Check if the connection can send RTCM data."""
        return self == ConnectionState.CONNECTED

    @property
    def should_retry(self) -> bool:
        """Check if the connection should be retried."""
        return self in (ConnectionState.DISCONNECTED, ConnectionState.ERROR)
