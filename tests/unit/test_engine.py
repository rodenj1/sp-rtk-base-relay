"""Tests for RelayEngine — high-level facade API.

Tests cover:
- Construction and initial state
- Lifecycle (start / stop / restart)
- Destination management (add / remove / start / stop)
- Status and event subscriptions
- Error handling (not running, duplicate names, unknown names)
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sp_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    InputConfig,
    TcpServerDestinationConfig,
)
from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.events import (
    ENGINE_STARTED,
    ENGINE_STOPPED,
    EventBus,
)
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.engine import RelayEngine
from sp_base_relay.exceptions import ConfigurationError, ServiceError


# ============================================================================
# Lightweight fakes (same pattern as broadcast_hub tests)
# ============================================================================


class FakeInputSource(InputSource):
    """Controllable fake input source for engine tests."""

    def __init__(self) -> None:
        super().__init__("fake")
        self._connected = False
        self._data_queue: queue.Queue[bytes | None] = queue.Queue()
        self.connect_should_fail = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        if self.connect_should_fail:
            return False
        self._connected = True
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        try:
            return self._data_queue.get(timeout=timeout or 0.1)
        except queue.Empty:
            return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}


class FakeDestination(BaseDestination):
    """Destination that records data without threading."""

    def __init__(
        self,
        name: str = "fake",
        filter_config: FilterConfig | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        if filter_config is None:
            filter_config = FilterConfig.pass_all()
        super().__init__(name, "fake", filter_config, queue_size)

    def start(self) -> None:  # type: ignore[override]
        self._running = True

    def stop(self) -> None:  # type: ignore[override]
        self._running = False

    def _connect(self) -> None:
        pass

    def _disconnect(self) -> None:
        pass

    def _send_data(self, data: bytes) -> None:
        pass

    def _is_connected(self) -> bool:
        return True

    def get_connection_info(self) -> dict[str, Any]:
        return {"name": self.name}


# ============================================================================
# Helpers
# ============================================================================


def _make_input_config() -> InputConfig:
    """Build a valid TCP input config for testing."""
    return InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 2101})


def _make_dest_config(name: str = "test-dest") -> DestinationConfig:
    """Build a minimal tcp_server destination config."""
    return DestinationConfig(
        name=name,
        type="tcp_server",
        enabled=True,
        filter=DestinationFilterConfig(mode="pass_all"),
        config=TcpServerDestinationConfig(
            host="0.0.0.0",
            port=5016,
        ),
    )


def _drain_events(sub: Any, max_events: int = 20, timeout: float = 0.2) -> list[str]:
    """Drain pending events from a subscription."""
    collected: list[str] = []
    for _ in range(max_events):
        event = sub.get_event(timeout=timeout)
        if event is None:
            break
        collected.append(event.event_type)
    return collected


# ============================================================================
# Tests — Construction
# ============================================================================


class TestRelayEngineInit:
    """RelayEngine.__init__ tests."""

    def test_creates_stopped(self) -> None:
        engine = RelayEngine(_make_input_config())
        assert engine.is_running is False

    def test_has_event_bus(self) -> None:
        engine = RelayEngine(_make_input_config())
        assert isinstance(engine.event_bus, EventBus)

    def test_destination_names_empty_when_stopped(self) -> None:
        engine = RelayEngine(_make_input_config())
        assert engine.get_destination_names() == []


# ============================================================================
# Tests — Lifecycle
# ============================================================================


class TestRelayEngineLifecycle:
    """start() / stop() tests."""

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_creates_hub_and_runs(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        fake_input = FakeInputSource()
        mock_isf.create_input_source.return_value = fake_input

        fake_dest = FakeDestination("d1")
        mock_df.create.return_value = fake_dest

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("d1")])
        try:
            assert engine.is_running is True
            assert engine.get_destination_names() == ["d1"]
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_with_no_destinations(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            assert engine.is_running is True
            assert engine.get_destination_names() == []
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_when_already_running_raises(
        self, mock_isf: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            with pytest.raises(ServiceError, match="already running"):
                engine.start()
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_stop_cleans_up(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = FakeDestination()

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config()])
        engine.stop()
        assert engine.is_running is False
        assert engine.get_destination_names() == []

    def test_stop_when_not_running_is_noop(self) -> None:
        engine = RelayEngine(_make_input_config())
        engine.stop()  # should not raise
        assert engine.is_running is False

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_stop_restart(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = FakeDestination()

        engine = RelayEngine(_make_input_config())

        # First run
        engine.start()
        assert engine.is_running is True
        engine.stop()
        assert engine.is_running is False

        # Second run — new input source created each time
        mock_isf.create_input_source.return_value = FakeInputSource()
        engine.start()
        assert engine.is_running is True
        engine.stop()
        assert engine.is_running is False


# ============================================================================
# Tests — Destination management
# ============================================================================


class TestDestinationManagement:
    """Hot add/remove/start/stop tests."""

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_add_destination(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            mock_df.create.return_value = FakeDestination("hot-add")
            name = engine.add_destination(_make_dest_config("hot-add"))
            assert name == "hot-add"
            assert "hot-add" in engine.get_destination_names()
        finally:
            engine.stop()

    def test_add_destination_when_not_running_raises(self) -> None:
        engine = RelayEngine(_make_input_config())
        with pytest.raises(ServiceError, match="not running"):
            engine.add_destination(_make_dest_config())

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_add_duplicate_name_raises(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = FakeDestination("dup")

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("dup")])
        try:
            mock_df.create.return_value = FakeDestination("dup")
            with pytest.raises(ConfigurationError, match="already exists"):
                engine.add_destination(_make_dest_config("dup"))
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_remove_destination(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = FakeDestination("removeme")

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("removeme")])
        try:
            engine.remove_destination("removeme")
            assert "removeme" not in engine.get_destination_names()
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_remove_nonexistent_raises(self, mock_isf: MagicMock) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            with pytest.raises(KeyError, match="not found"):
                engine.remove_destination("nope")
        finally:
            engine.stop()

    def test_remove_when_not_running_raises(self) -> None:
        engine = RelayEngine(_make_input_config())
        with pytest.raises(ServiceError, match="not running"):
            engine.remove_destination("any")

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_stop_destination(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        fake_dest = FakeDestination("d1")
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = fake_dest

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("d1")])
        try:
            engine.stop_destination("d1")
            assert fake_dest.enabled is False
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_stop_destination_nonexistent_raises(
        self, mock_isf: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            with pytest.raises(KeyError, match="not found"):
                engine.stop_destination("nope")
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_destination(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        fake_dest = FakeDestination("d1")
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = fake_dest

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("d1")])
        try:
            engine.stop_destination("d1")
            assert fake_dest.enabled is False
            engine.start_destination("d1")
            assert fake_dest.enabled is True
        finally:
            engine.stop()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_start_destination_nonexistent_raises(
        self, mock_isf: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        try:
            with pytest.raises(KeyError, match="not found"):
                engine.start_destination("nope")
        finally:
            engine.stop()

    def test_start_destination_when_not_running_raises(self) -> None:
        engine = RelayEngine(_make_input_config())
        with pytest.raises(ServiceError, match="not running"):
            engine.start_destination("any")

    def test_stop_destination_when_not_running_raises(self) -> None:
        engine = RelayEngine(_make_input_config())
        with pytest.raises(ServiceError, match="not running"):
            engine.stop_destination("any")


# ============================================================================
# Tests — Status
# ============================================================================


class TestRelayEngineStatus:
    """get_status() tests."""

    @patch("sp_base_relay.engine.DestinationFactory")
    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_get_status_returns_relay_status(
        self, mock_isf: MagicMock, mock_df: MagicMock
    ) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()
        mock_df.create.return_value = FakeDestination("d1")

        engine = RelayEngine(_make_input_config())
        engine.start([_make_dest_config("d1")])
        try:
            status = engine.get_status()
            assert status.running is True
            assert len(status.destinations) == 1
            assert status.destinations[0].name == "d1"
        finally:
            engine.stop()

    def test_get_status_when_not_running_raises(self) -> None:
        engine = RelayEngine(_make_input_config())
        with pytest.raises(ServiceError, match="not running"):
            engine.get_status()


# ============================================================================
# Tests — Events
# ============================================================================


class TestRelayEngineEvents:
    """Event subscription and retrieval tests."""

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_subscribe_before_start(self, mock_isf: MagicMock) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        sub = engine.subscribe_events()
        try:
            engine.start()
            events = _drain_events(sub)
            assert ENGINE_STARTED in events
        finally:
            engine.stop()
            sub.close()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_stop_emits_engine_stopped(self, mock_isf: MagicMock) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        sub = engine.subscribe_events()
        engine.start()
        engine.stop()
        events = _drain_events(sub)
        assert ENGINE_STOPPED in events
        sub.close()

    @patch("sp_base_relay.engine.InputSourceFactory")
    def test_get_recent_events(self, mock_isf: MagicMock) -> None:
        mock_isf.create_input_source.return_value = FakeInputSource()

        engine = RelayEngine(_make_input_config())
        engine.start()
        engine.stop()
        recent = engine.get_recent_events()
        event_types = [e.event_type for e in recent]
        assert ENGINE_STARTED in event_types
        assert ENGINE_STOPPED in event_types

    def test_subscribe_events_returns_subscription(self) -> None:
        engine = RelayEngine(_make_input_config())
        sub = engine.subscribe_events()
        assert sub is not None
        # Should be able to close without error
        sub.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
