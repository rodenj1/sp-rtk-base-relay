"""Core components for SP-Base-Relay RTCM connection management.

This package contains the core implementation for RTCM server connections,
including authentication, heartbeat monitoring, and connection management.
"""

from .connection_states import ConnectionState
from .rtcm_client import RTCMClient

__all__ = [
    "ConnectionState",
    "RTCMClient",
]
