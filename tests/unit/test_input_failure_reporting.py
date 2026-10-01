"""Tests for how the Relay reports why its input can't connect.

Seams under test:
- RelayEngine.get_status(): a real engine and hub with a fake input that
  connects, then drops and fails to reconnect. The fake's own tiny reconnect
  policy keeps the hub's real reconnect loop fast.
- The Prometheus output: MetricsCollector.update_all() fed a real hub that has
  seen those failures, read back from the registry.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from sp_rtk_base_relay.config import InputConfig
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.input_sources.base_input import (
    InputSource,
    ReconnectPolicy,
)
from sp_rtk_base_relay.engine import RelayEngine
from sp_rtk_base_relay.exceptions import NtripConnectionError, NtripFailure
from sp_rtk_base_relay.metrics import MetricsCollector

REFUSED = None  # in FakeInput.outcomes: connect() returns False without raising


class FakeInput(InputSource):
    """An input whose connect() fails as told, then succeeds.

    Each connect() takes the next of ``outcomes`` (raise it, or return False for
    REFUSED); once they run out, it raises ``failure`` if set, else succeeds.
    """

    def __init__(self) -> None:
        super().__init__("fake")
        self.outcomes: list[Exception | None] = []
        self.failure: Exception | None = None
        self.read_failure: Exception | None = None  # raised once by read_data()

    @property
    def reconnect_policy(self) -> ReconnectPolicy:
        return ReconnectPolicy(initial_delay=0.01, max_delay=0.02, multiplier=2.0)

    def connect(self) -> bool:
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            self._update_connection_stats(False)
            if outcome is None:  # REFUSED
                return False
            raise outcome
        if self.failure is not None:
            self._update_connection_stats(False)
            raise self.failure
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        time.sleep(0.01)
        if self.read_failure is not None:
            failure, self.read_failure = self.read_failure, None
            self._connected = False
            raise failure
        return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}

    def drop(self) -> None:
        """The connection goes away; the hub notices and reconnects."""
        self._connected = False


def _auth_rejected() -> NtripConnectionError:
    return NtripConnectionError(
        "caster.example:2101/MP1: 'HTTP/1.1 401 Unauthorized'",
        reason=NtripFailure.AUTH,
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        time.sleep(0.01)


@pytest.fixture
def source() -> FakeInput:
    return FakeInput()


@pytest.fixture
def engine(source: FakeInput) -> Iterator[RelayEngine]:
    with patch("sp_rtk_base_relay.engine.InputSourceFactory") as factory:
        factory.create_input_source.return_value = source
        relay = RelayEngine(
            InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 2101})
        )
        relay.start([])
        yield relay
        relay.stop()


def _last_error(engine: RelayEngine) -> str | None:
    return engine.get_status().input.last_error


class TestStatusLastError:
    def test_a_healthy_input_has_no_last_error(self, engine: RelayEngine) -> None:
        assert _last_error(engine) is None

    def test_a_failed_reconnect_shows_its_error_until_the_input_reconnects(
        self, engine: RelayEngine, source: FakeInput
    ) -> None:
        source.failure = _auth_rejected()
        source.drop()

        _wait_for(lambda: _last_error(engine) is not None)
        assert "401 Unauthorized" in str(_last_error(engine))

        source.failure = None
        _wait_for(lambda: engine.get_status().input.connected)
        assert _last_error(engine) is None

    def test_an_untyped_error_is_shown_as_text(
        self, engine: RelayEngine, source: FakeInput
    ) -> None:
        source.failure = OSError("No route to host")
        source.drop()

        _wait_for(lambda: _last_error(engine) == "No route to host")


# ----------------------------------------------------------------------------
# Prometheus: input connection failures by reason
# ----------------------------------------------------------------------------

FAILURES = "sp_rtk_base_relay_input_connection_failures_total"


@pytest.fixture
def metrics() -> Iterator[MetricsCollector]:
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)
    yield MetricsCollector()
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)


@pytest.fixture
def hub(source: FakeInput) -> Iterator[BroadcastHub]:
    broadcast_hub = BroadcastHub(source, [])
    yield broadcast_hub
    broadcast_hub.stop()


def _failures(reason: str) -> float:
    return REGISTRY.get_sample_value(FAILURES, {"reason": reason}) or 0.0


def _reconnect_through(
    hub: BroadcastHub, source: FakeInput, outcomes: list[Exception | None]
) -> None:
    """Start the hub, drop the input, and let it fail ``outcomes`` before reconnecting."""
    hub.start()
    source.outcomes = list(outcomes)
    source.drop()
    _wait_for(lambda: not source.outcomes and source.is_connected)


class TestFailuresMetric:
    def test_each_failure_is_counted_under_its_reason(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        mountpoint = NtripConnectionError("404", reason=NtripFailure.MOUNTPOINT)
        metrics.update_all([], hub=hub, input_source=source)  # baseline

        _reconnect_through(
            hub, source, [_auth_rejected(), _auth_rejected(), mountpoint]
        )
        metrics.update_all([], hub=hub, input_source=source)

        assert _failures("auth") == 2
        assert _failures("mountpoint") == 1
        assert _failures("connect") == 0

    def test_inputs_without_typed_errors_count_as_connect(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        metrics.update_all([], hub=hub, input_source=source)

        _reconnect_through(hub, source, [OSError("refused"), REFUSED])
        metrics.update_all([], hub=hub, input_source=source)

        assert _failures("connect") == 2

    def test_a_failed_start_is_counted(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        # The service starts the hub before its first metrics update
        source.outcomes = [_auth_rejected()]

        with pytest.raises(NtripConnectionError):
            hub.start()
        metrics.update_all([], hub=hub, input_source=source)

        assert _failures("auth") == 1

    def test_counts_only_grow_by_new_failures(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        metrics.update_all([], hub=hub, input_source=source)
        _reconnect_through(hub, source, [OSError("refused")])
        metrics.update_all([], hub=hub, input_source=source)
        metrics.update_all([], hub=hub, input_source=source)  # nothing new

        assert _failures("connect") == 1

    def test_a_typed_error_while_reading_is_counted(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        # e.g. the NTRIP input's data timeout: connected, but no bytes arrive
        metrics.update_all([], hub=hub, input_source=source)
        hub.start()

        source.read_failure = NtripConnectionError(
            "no data for 30s", reason=NtripFailure.DATA_TIMEOUT
        )
        _wait_for(lambda: source.read_failure is None and source.is_connected)
        metrics.update_all([], hub=hub, input_source=source)

        assert _failures("data_timeout") == 1

    def test_an_untyped_error_while_reading_is_not_a_failed_connection(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        metrics.update_all([], hub=hub, input_source=source)
        hub.start()

        source.read_failure = OSError("Connection reset by peer")
        _wait_for(lambda: source.read_failure is None and source.is_connected)
        metrics.update_all([], hub=hub, input_source=source)

        assert REGISTRY.get_sample_value(FAILURES, {"reason": "connect"}) == 0
