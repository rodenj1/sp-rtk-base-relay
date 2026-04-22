"""Factory for creating BaseDestination instances from configuration.

This module provides a registry-based factory that converts
``DestinationConfig`` objects (parsed from YAML) into concrete
``BaseDestination`` instances.  Concrete destination types register
themselves via ``DestinationFactory.register()``.

Follows the same pattern as ``InputSourceFactory`` in
``core/input_sources/input_factory.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sp_rtk_base_relay.config import DestinationConfig
from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
from sp_rtk_base_relay.exceptions import ConfigurationError, DestinationError

logger = logging.getLogger(__name__)

# Type alias for a builder callable.
# Receives (name, FilterConfig, type-specific config dataclass) and
# returns a BaseDestination.
DestinationBuilder = Callable[[DestinationConfig], BaseDestination]


class DestinationFactory:
    """Registry-based factory for creating destination instances.

    Concrete destination types register themselves during module import
    (e.g. ``SurePathDestination`` will call ``register("surepath", …)``
    when it is imported in Phase 2).

    Usage::

        destinations = DestinationFactory.create_all(config.destinations)
    """

    # Map from destination type name to builder callable
    _builders: dict[str, DestinationBuilder] = {}

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, dest_type: str, builder: DestinationBuilder) -> None:
        """Register a builder for *dest_type*.

        Args:
            dest_type: Destination type identifier (e.g. ``"surepath"``).
            builder: Callable that receives a ``DestinationConfig`` and
                returns a ``BaseDestination``.

        Raises:
            ValueError: If *dest_type* is empty.
        """
        if not dest_type:
            raise ValueError("dest_type must not be empty")
        cls._builders[dest_type] = builder
        logger.info("Registered destination type: %s", dest_type)

    @classmethod
    def unregister(cls, dest_type: str) -> bool:
        """Remove a registered builder.

        Args:
            dest_type: Type identifier to remove.

        Returns:
            ``True`` if the type was registered (and removed), ``False``
            otherwise.
        """
        if dest_type in cls._builders:
            del cls._builders[dest_type]
            logger.info("Unregistered destination type: %s", dest_type)
            return True
        return False

    @classmethod
    def get_available_types(cls) -> list[str]:
        """Return the currently registered destination type names."""
        return list(cls._builders.keys())

    @classmethod
    def is_registered(cls, dest_type: str) -> bool:
        """Check whether *dest_type* has a registered builder."""
        return dest_type in cls._builders

    # ------------------------------------------------------------------
    # Creation helpers
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, dest_config: DestinationConfig) -> BaseDestination:
        """Create a single ``BaseDestination`` from *dest_config*.

        Args:
            dest_config: Parsed destination configuration entry.

        Returns:
            A fully constructed ``BaseDestination`` instance.

        Raises:
            ConfigurationError: If the destination type is not registered.
            DestinationError: If the builder fails.
        """
        dest_type = dest_config.type

        if dest_type not in cls._builders:
            available = ", ".join(cls.get_available_types()) or "(none)"
            raise ConfigurationError(
                f"Unknown destination type '{dest_type}'. Available types: {available}",
                config_key=f"destinations[{dest_config.name}].type",
            )

        builder = cls._builders[dest_type]

        try:
            destination = builder(dest_config)
        except (ConfigurationError, DestinationError):
            raise
        except Exception as exc:
            raise DestinationError(
                f"Failed to create destination '{dest_config.name}' "
                f"(type={dest_type}): {exc}",
                destination_name=dest_config.name,
            ) from exc

        # Apply enabled flag from config
        destination.enabled = dest_config.enabled

        logger.info(
            "Created destination '%s' (type=%s, enabled=%s, filter=%s)",
            dest_config.name,
            dest_type,
            dest_config.enabled,
            dest_config.filter.mode,
        )
        return destination

    @classmethod
    def create_all(
        cls,
        configs: list[DestinationConfig],
        *,
        skip_disabled: bool = False,
    ) -> list[BaseDestination]:
        """Create ``BaseDestination`` instances for every config entry.

        Args:
            configs: List of ``DestinationConfig`` from the parsed YAML.
            skip_disabled: If ``True``, entries with ``enabled=False`` are
                silently skipped rather than created.

        Returns:
            List of ``BaseDestination`` instances (order matches *configs*).

        Raises:
            ConfigurationError: If any destination type is unknown or if
                the resulting list would be empty.
            DestinationError: If any builder fails.
        """
        if not configs:
            raise ConfigurationError(
                "At least one destination configuration is required",
                config_key="destinations",
            )

        destinations: list[BaseDestination] = []

        for cfg in configs:
            if skip_disabled and not cfg.enabled:
                logger.info("Skipping disabled destination '%s'", cfg.name)
                continue
            destinations.append(cls.create(cfg))

        if not destinations:
            raise ConfigurationError(
                "No destinations to create (all disabled?)",
                config_key="destinations",
            )

        logger.info(
            "Created %d destination(s): %s",
            len(destinations),
            ", ".join(d.name for d in destinations),
        )
        return destinations

    @classmethod
    def get_type_info(cls) -> dict[str, dict[str, Any]]:
        """Return diagnostic info for every registered type.

        Returns:
            Mapping of type name → info dict with ``registered=True``.
        """
        return {
            t: {"registered": True, "builder": repr(b)}
            for t, b in cls._builders.items()
        }
