"""SP-Base-Relay: RTCM relay service for custom GPS correction servers."""

__version__ = "2.1.2"

# v2.1 public API — RelayEngine facade
# v2.1 public API — Event system
from sp_rtk_base_relay.core.events import EventBus, EventSubscription, RelayEvent

# v2.1 public API — Typed status snapshots
from sp_rtk_base_relay.core.status import (
    DestinationStatus,
    InputStatus,
    RelayStatus,
)
from sp_rtk_base_relay.engine import RelayEngine

__all__ = [
    "DestinationStatus",
    "EventBus",
    "EventSubscription",
    "InputStatus",
    "RelayEngine",
    "RelayEvent",
    "RelayStatus",
    "__version__",
]
