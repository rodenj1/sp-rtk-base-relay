"""Destination module package for v2.0 multi-destination architecture.

This package contains the base destination interface, concrete destination
implementations, and factory for creating destinations from configuration.

Exports:
    BaseDestination: Abstract base class for all destinations
    DestinationStats: Per-destination metrics dataclass
    DestinationFactory: Registry-based factory for creating destinations
    SurePathDestination: Sure-Path server destination (wraps RTCMClient)
"""

from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DestinationStats,
)
from sp_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)

# Import registers the "surepath" builder with DestinationFactory
from sp_base_relay.core.destinations.surepath_destination import (  # noqa: F401
    SurePathDestination,
)

# Import registers the "ntrip" builder with DestinationFactory
from sp_base_relay.core.destinations.ntrip_destination import (  # noqa: F401
    NtripDestination,
)

__all__ = [
    "BaseDestination",
    "DestinationFactory",
    "DestinationStats",
    "NtripDestination",
    "SurePathDestination",
]
