"""Destination module package for v2.0 multi-destination architecture.

This package contains the base destination interface, concrete destination
implementations, and factory for creating destinations from configuration.

Exports:
    BaseDestination: Abstract base class for all destinations
    DestinationStats: Per-destination metrics dataclass
    DestinationFactory: Registry-based factory for creating destinations
"""

from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DestinationStats,
)
from sp_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)

__all__ = [
    "BaseDestination",
    "DestinationFactory",
    "DestinationStats",
]
