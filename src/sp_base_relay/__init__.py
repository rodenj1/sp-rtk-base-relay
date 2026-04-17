"""SP-Base-Relay: RTCM relay service for custom GPS correction servers."""

__version__ = "2.1.0"

# v2.1 public API — RelayEngine facade
from sp_base_relay.engine import RelayEngine

# v2.1 public API — Event system
from sp_base_relay.core.events import EventBus, EventSubscription, RelayEvent

# v2.1 public API — Typed status snapshots
from sp_base_relay.core.status import (
    DestinationStatus,
    InputStatus,
    RelayStatus,
)

__all__ = [
    "__version__",
    "RelayEngine",
    "EventBus",
    "EventSubscription",
    "RelayEvent",
    "RelayStatus",
    "DestinationStatus",
    "InputStatus",
]
