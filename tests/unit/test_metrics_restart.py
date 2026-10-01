"""Tests for metrics that must keep counting after an engine restart.

Seam under test: a RelayEngine with a MetricsCollector, updated through
RelayEngine.update_metrics(), stopped and started again with the same
collector. Each start() creates a new hub, input source and destinations
(the factories are patched to hand out fakes), whose stats start at 0.
"""

import queue
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from sp_rtk_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    InputConfig,
    TcpServerDestinationConfig,
)
from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
from sp_rtk_base_relay.core.input_sources.base_input import InputSource
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.engine import RelayEngine
from sp_rtk_base_relay.metrics import MetricsCollector

INPUT_BYTES = "sp_rtk_base_relay_input_bytes_received_total"
HUB_BYTES = "sp_rtk_base_relay_hub_bytes_received_total"
DEST_BYTES = "sp_rtk_base_relay_dest_bytes_sent_total"


class FakeInput(InputSource):
    """Hands the hub whatever is pushed to it."""

    def __init__(self) -> None:
        super().__init__("fake")
        self.data: queue.Queue[bytes] = queue.Queue()

    def connect(self) -> bool:
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        try:
            chunk = self.data.get(timeout=0.05)
        except queue.Empty:
            return None
        self._update_read_stats(chunk)
        return chunk

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}


class FakeDestination(BaseDestination):
    """A destination whose sends always succeed (its real thread runs)."""

    def __init__(self) -> None:
        super().__init__("lan", "fake", FilterConfig.pass_all())

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


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        time.sleep(0.01)


@pytest.fixture
def metrics() -> Iterator[MetricsCollector]:
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)
    yield MetricsCollector()
    for collector in list(REGISTRY._collector_to_names):  # pyright: ignore[reportPrivateUsage]
        REGISTRY.unregister(collector)


class EngineRun:
    """One engine run's fresh input and destination."""

    def __init__(self) -> None:
        self.input = FakeInput()
        self.destination = FakeDestination()


@pytest.fixture
def engine(metrics: MetricsCollector) -> Iterator[tuple[RelayEngine, list[EngineRun]]]:
    runs: list[EngineRun] = []

    def _input(*_args: object) -> FakeInput:
        runs.append(EngineRun())
        return runs[-1].input

    def _destination(*_args: object) -> FakeDestination:
        return runs[-1].destination

    with (
        patch("sp_rtk_base_relay.engine.InputSourceFactory") as inputs,
        patch("sp_rtk_base_relay.engine.DestinationFactory") as destinations,
    ):
        inputs.create_input_source.side_effect = _input
        destinations.create.side_effect = _destination
        relay = RelayEngine(
            InputConfig(source="tcp", config={"host": "127.0.0.1", "port": 2101}),
            metrics_collector=metrics,
        )
        yield relay, runs
        if relay.is_running:
            relay.stop()


def _start(engine: RelayEngine) -> None:
    engine.start(
        [
            DestinationConfig(
                name="lan",
                type="tcp_server",
                enabled=True,
                filter=DestinationFilterConfig(mode="pass_all"),
                config=TcpServerDestinationConfig(host="127.0.0.1", port=5016),
            )
        ]
    )


def _push_through(run: EngineRun, size: int) -> None:
    """Push ``size`` bytes through this run and wait until they're sent on."""
    sent_before = run.destination.stats.bytes_sent
    run.input.data.put(b"\xd3" * size)
    _wait_for(lambda: run.destination.stats.bytes_sent == sent_before + size)


def _counter(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_counting_carries_on_after_a_restart(
    engine: tuple[RelayEngine, list[EngineRun]],
) -> None:
    relay, runs = engine
    _start(relay)
    relay.update_metrics()  # first update: the baseline
    _push_through(runs[-1], 100)
    relay.update_metrics()
    assert _counter(INPUT_BYTES) == 100

    relay.stop()
    relay.update_metrics()
    _start(relay)  # a new hub, input and destination, all counting from 0
    _push_through(runs[-1], 30)
    relay.update_metrics()

    assert _counter(INPUT_BYTES) == 130
    assert _counter(HUB_BYTES) == 130
    assert _counter(DEST_BYTES, {"destination": "lan"}) == 130
