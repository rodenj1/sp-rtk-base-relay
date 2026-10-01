"""Tests for the input reconnect counts in the status snapshot and the metrics.

Seam under test: build_relay_status() and MetricsCollector.update_all(), fed a
real BroadcastHub whose fake input connected at start and then reconnected.
The fake's own tiny reconnect policy keeps the hub's real reconnect loop fast.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from prometheus_client import REGISTRY

from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.input_sources.base_input import (
    InputSource,
    ReconnectPolicy,
)
from sp_rtk_base_relay.core.status import build_relay_status
from sp_rtk_base_relay.metrics import MetricsCollector

ATTEMPTS = "sp_rtk_base_relay_input_reconnect_attempts_total"
SUCCESSES = "sp_rtk_base_relay_input_reconnect_successes_total"


class FakeInput(InputSource):
    """Connects, unless ``fail_next`` connect() calls are still to fail."""

    def __init__(self) -> None:
        super().__init__("fake")
        self.fail_next = 0

    @property
    def reconnect_policy(self) -> ReconnectPolicy:
        return ReconnectPolicy(initial_delay=0.01, max_delay=0.02, multiplier=2.0)

    def connect(self) -> bool:
        if self.fail_next:
            self.fail_next -= 1
            self._update_connection_stats(False)
            return False
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        time.sleep(0.01)
        return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        time.sleep(0.01)


@pytest.fixture
def source() -> FakeInput:
    return FakeInput()


@pytest.fixture
def hub(source: FakeInput) -> Iterator[BroadcastHub]:
    broadcast_hub = BroadcastHub(source, [])
    broadcast_hub.start()  # the first connect: not a reconnect
    yield broadcast_hub
    broadcast_hub.stop()


@pytest.fixture
def metrics() -> Iterator[MetricsCollector]:
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)
    yield MetricsCollector()
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)


def _reconnect_after_one_failure(hub: BroadcastHub, source: FakeInput) -> None:
    source.fail_next = 1
    source.disconnect()  # the input drops
    _wait_for(lambda: hub.stats.input_reconnect_successes == 1)


class TestStatus:
    def test_an_input_that_never_dropped_shows_no_reconnects(
        self, hub: BroadcastHub, source: FakeInput
    ) -> None:
        status = build_relay_status(hub, source).input

        assert (status.reconnect_attempts, status.reconnect_successes) == (0, 0)

    def test_each_reconnect_attempt_counts_once(
        self, hub: BroadcastHub, source: FakeInput
    ) -> None:
        _reconnect_after_one_failure(hub, source)

        status = build_relay_status(hub, source).input

        assert (status.reconnect_attempts, status.reconnect_successes) == (2, 1)


class TestMetrics:
    def test_an_input_that_never_dropped_shows_no_reconnects(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        metrics.update_all([], hub=hub, input_source=source)
        metrics.update_all([], hub=hub, input_source=source)

        assert REGISTRY.get_sample_value(ATTEMPTS) == 0
        assert REGISTRY.get_sample_value(SUCCESSES) == 0

    def test_each_reconnect_attempt_counts_once(
        self, metrics: MetricsCollector, hub: BroadcastHub, source: FakeInput
    ) -> None:
        # The service starts the hub before its first metrics update
        _reconnect_after_one_failure(hub, source)

        metrics.update_all([], hub=hub, input_source=source)
        metrics.update_all([], hub=hub, input_source=source)

        assert REGISTRY.get_sample_value(ATTEMPTS) == 2
        assert REGISTRY.get_sample_value(SUCCESSES) == 1
