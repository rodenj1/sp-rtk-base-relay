"""RelayEngine — high-level facade for programmatic relay control.

This module provides :class:`RelayEngine`, the recommended entry-point
for applications that embed *sp-rtk-base-relay* as a Python dependency.

Typical usage::

    from sp_rtk_base_relay.engine import RelayEngine
    from sp_rtk_base_relay.config import InputConfig, DestinationConfig

    engine = RelayEngine(InputConfig(source="tcp", config={"host": "...", "port": 2101}))
    engine.start([dest_config_1, dest_config_2])

    # Hot-add a destination while running
    engine.add_destination(dest_config_3)

    # Get a typed status snapshot
    status = engine.get_status()

    # Subscribe to real-time events
    sub = engine.subscribe_events()
    event = sub.get_event(timeout=1.0)
    sub.close()

    engine.stop()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sp_rtk_base_relay.config import DestinationConfig, InputConfig
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.destinations.destination_factory import DestinationFactory
from sp_rtk_base_relay.core.events import (
    ENGINE_STARTED,
    ENGINE_STOPPED,
    EventBus,
    EventSubscription,
    RelayEvent,
)
from sp_rtk_base_relay.core.input_sources.input_factory import InputSourceFactory
from sp_rtk_base_relay.core.status import RelayStatus, build_relay_status
from sp_rtk_base_relay.exceptions import ConfigurationError, ServiceError

if TYPE_CHECKING:
    from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
    from sp_rtk_base_relay.core.input_sources.base_input import InputSource
    from sp_rtk_base_relay.metrics import MetricsCollector

logger = logging.getLogger(__name__)


class RelayEngine:
    """High-level relay engine for programmatic control.

    This is the recommended API for applications that embed
    *sp-rtk-base-relay* as a dependency.  For standalone CLI usage,
    run ``sp-rtk-base-relay --config config.yaml`` which uses this
    engine internally.

    The engine is created in a **stopped** state.  Call :meth:`start`
    to begin relaying data.

    Args:
        input_config: Input source configuration (serial, TCP, bluetooth, etc.).
        metrics_collector: Optional :class:`MetricsCollector` wired into
            the event bus for Prometheus telemetry. When provided, the
            engine will push events to ``events_emitted_total{event_type}``
            and poll the engine/hub state via :meth:`update_metrics`.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        input_config: InputConfig,
        metrics_collector: MetricsCollector | None = None,
    ) -> None:
        self._input_config = input_config
        self._metrics: MetricsCollector | None = metrics_collector
        self._event_bus = EventBus(metrics_collector=metrics_collector)
        self._input_source: InputSource | None = None
        self._hub: BroadcastHub | None = None
        self._running = False

        logger.debug("RelayEngine created for input source=%s", input_config.source)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, destinations: list[DestinationConfig] | None = None) -> None:
        """Start the relay engine.

        Connects the input source, creates destinations from configs,
        starts the :class:`BroadcastHub`, and begins relaying data.

        Args:
            destinations: Optional list of destination configs to start
                with.  If ``None``, starts with no destinations (add
                them later via :meth:`add_destination`).

        Raises:
            ServiceError: If engine is already running.
            ConnectionError: If input source fails to connect.
            ConfigurationError: If a destination config is invalid.
        """
        if self._running:
            raise ServiceError("Engine is already running")

        # 1. Create input source
        self._input_source = InputSourceFactory.create_input_source(
            self._input_config.source,
            self._input_config.config,
        )

        # 2. Create destination objects from configs
        dest_objects: list[BaseDestination] = []
        for dc in destinations or []:
            dest_objects.append(DestinationFactory.create(dc))

        # 3. Create and start BroadcastHub
        self._hub = BroadcastHub(
            input_source=self._input_source,
            destinations=dest_objects,
            event_bus=self._event_bus,
        )
        self._hub.start()
        self._running = True

        self._event_bus.emit(
            ENGINE_STARTED,
            f"RelayEngine started with {len(dest_objects)} destination(s)",
            destination_count=len(dest_objects),
            input_source=self._input_config.source,
        )
        logger.info(
            "RelayEngine started: input=%s, destinations=%d",
            self._input_config.source,
            len(dest_objects),
        )

    def stop(self) -> None:
        """Stop the relay engine gracefully.

        Stops all destinations, disconnects the input source, and
        releases all resources.  The engine can be started again
        after stopping.
        """
        if not self._running:
            return

        if self._hub is not None:
            self._hub.stop()
            self._hub = None

        self._input_source = None
        self._running = False

        self._event_bus.emit(ENGINE_STOPPED, "RelayEngine stopped")
        logger.info("RelayEngine stopped")

    @property
    def is_running(self) -> bool:
        """``True`` if the engine is actively relaying data."""
        return self._running

    # ------------------------------------------------------------------
    # Destination management
    # ------------------------------------------------------------------

    def add_destination(self, config: DestinationConfig) -> str:
        """Add a destination while running (hot-add).

        Creates the destination from *config*, starts its thread,
        and begins routing data to it.

        Args:
            config: Destination configuration.

        Returns:
            The destination name.

        Raises:
            ServiceError: If the engine is not running.
            ConfigurationError: If the config is invalid or the name
                already exists.
        """
        self._require_running("add_destination")
        assert self._hub is not None  # guarded by _require_running

        dest = DestinationFactory.create(config)
        try:
            self._hub.add_destination(dest)
        except ValueError as exc:
            raise ConfigurationError(str(exc)) from exc

        logger.info("Destination added: %s", config.name)
        return config.name

    def remove_destination(self, name: str) -> None:
        """Remove a destination (hot-remove).

        Stops the destination thread, disconnects from the remote
        server, and removes it from the routing list.

        Args:
            name: Destination name to remove.

        Raises:
            ServiceError: If the engine is not running.
            KeyError: If the destination name is not found.
        """
        self._require_running("remove_destination")
        assert self._hub is not None

        removed = self._hub.remove_destination(name)
        if removed is None:
            raise KeyError(f"Destination '{name}' not found")

        logger.info("Destination removed: %s", name)

    def start_destination(self, name: str) -> None:
        """Start (resume) a specific destination.

        Re-enables data routing and starts the destination thread.

        Args:
            name: Destination name to start.

        Raises:
            ServiceError: If the engine is not running.
            KeyError: If the destination name is not found.
        """
        self._require_running("start_destination")
        assert self._hub is not None

        if not self._hub.start_destination(name):
            raise KeyError(f"Destination '{name}' not found")

    def stop_destination(self, name: str) -> None:
        """Stop (pause) a specific destination.

        Stops the destination thread and disables data routing.
        Other destinations continue unaffected.

        Args:
            name: Destination name to stop.

        Raises:
            ServiceError: If the engine is not running.
            KeyError: If the destination name is not found.
        """
        self._require_running("stop_destination")
        assert self._hub is not None

        if not self._hub.stop_destination(name):
            raise KeyError(f"Destination '{name}' not found")

    def get_destination_names(self) -> list[str]:
        """Return names of all registered destinations.

        Returns:
            A list of destination names (empty list if engine not running).
        """
        if self._hub is None:
            return []
        return self._hub.get_destination_names()

    # ------------------------------------------------------------------
    # Status & events
    # ------------------------------------------------------------------

    def get_status(self) -> RelayStatus:
        """Get a typed snapshot of current relay state.

        Returns:
            Frozen :class:`RelayStatus` dataclass with input, hub,
            and per-destination status.

        Raises:
            ServiceError: If the engine is not running.
        """
        self._require_running("get_status")
        assert self._hub is not None
        assert self._input_source is not None
        return build_relay_status(self._hub, self._input_source)

    def subscribe_events(self) -> EventSubscription:
        """Subscribe to real-time relay events.

        Returns:
            An :class:`EventSubscription` that yields
            :class:`RelayEvent` objects.  Call ``.close()`` when done.
        """
        return self._event_bus.subscribe()

    def get_recent_events(self, count: int = 50) -> list[RelayEvent]:
        """Get recent events from the ring buffer.

        Args:
            count: Maximum number of events to return.

        Returns:
            List of recent :class:`RelayEvent` objects (newest last).
        """
        return self._event_bus.get_recent(count)

    @property
    def event_bus(self) -> EventBus:
        """Direct access to the event bus (advanced usage)."""
        return self._event_bus

    # ------------------------------------------------------------------
    # Metrics integration
    # ------------------------------------------------------------------

    @property
    def metrics_collector(self) -> MetricsCollector | None:
        """The :class:`MetricsCollector` attached to this engine, if any."""
        return self._metrics

    def update_metrics(self) -> None:
        """Refresh all Prometheus metrics from live engine state.

        No-op if no :class:`MetricsCollector` was supplied at
        construction. Safe to call whether the engine is running or
        stopped — when stopped, the collector sees the engine's
        ``engine_running`` flag flip to 0.
        """
        if self._metrics is None:
            return

        destinations: list[BaseDestination] = (
            list(self._hub.destinations) if self._hub is not None else []
        )
        self._metrics.update_all(
            destinations=destinations,
            hub=self._hub,
            input_source=self._input_source,
            event_bus=self._event_bus,
            engine_running=self._running,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_running(self, method_name: str) -> None:
        """Raise :class:`ServiceError` if the engine is not running."""
        if not self._running:
            raise ServiceError(f"Cannot call {method_name}(): engine is not running")
