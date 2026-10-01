"""Tests for how the hub reconnects its input source.

Seam under test: BroadcastHub's input reconnect loop (what its input thread runs
when the input drops), with a fake input that fails a set number of times and
can supply its own reconnect policy or report a persistent failure. The hub's
wait between attempts is injected: it records each delay and returns at once.
"""

from typing import Any

import pytest

from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.input_sources.base_input import (
    InputSource,
    ReconnectPolicy,
)


class FakeInput(InputSource):
    """An input whose connect() fails ``fail_times`` times, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        super().__init__("fake")
        self.fail_times = fail_times
        self.connect_calls: int = 0

    def connect(self) -> bool:
        self.connect_calls += 1
        if self.connect_calls <= self.fail_times:
            return False
        self._connected = True
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}


class PolicyInput(FakeInput):
    """A fake input with its own reconnect policy, whose chosen failures are persistent."""

    def __init__(
        self,
        fail_times: int,
        policy: ReconnectPolicy,
        persistent_failures: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(fail_times)
        self.policy = policy
        self.persistent_failures = persistent_failures  # 1-based connect() calls

    @property
    def reconnect_policy(self) -> ReconnectPolicy:
        return self.policy

    @property
    def last_failure_persistent(self) -> bool:
        return self.connect_calls in self.persistent_failures


class WaitRecorder:
    """Stands in for the hub's wait: records each delay, never sleeps."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, timeout: float) -> bool:
        self.delays.append(timeout)
        return False  # not stopped


class StoppingWait(WaitRecorder):
    """A wait that reports the hub is stopping."""

    def __call__(self, timeout: float) -> bool:
        super().__call__(timeout)
        return True


@pytest.fixture
def wait() -> WaitRecorder:
    return WaitRecorder()


def _reconnect(source: InputSource, wait: WaitRecorder) -> BroadcastHub:
    hub = BroadcastHub(source, [], reconnect_wait=wait)
    hub._running = True  # pyright: ignore[reportPrivateUsage]  # as after start()
    hub._reconnect_input()  # pyright: ignore[reportPrivateUsage]
    return hub


def test_an_input_without_a_policy_keeps_2s_to_60s_doubling(
    wait: WaitRecorder,
) -> None:
    source = FakeInput(fail_times=7)

    hub = _reconnect(source, wait)

    assert wait.delays == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]
    assert hub.stats.input_reconnect_attempts == source.connect_calls == 8
    assert hub.stats.input_reconnect_successes == 1


def test_an_inputs_own_policy_is_honoured(wait: WaitRecorder) -> None:
    source = PolicyInput(
        fail_times=6,
        policy=ReconnectPolicy(initial_delay=10.0, max_delay=120.0, multiplier=3.0),
    )

    hub = _reconnect(source, wait)

    assert wait.delays == [10.0, 30.0, 90.0, 120.0, 120.0, 120.0]
    assert hub.stats.input_reconnect_attempts == source.connect_calls == 7


def test_a_persistent_failure_waits_the_policys_maximum(wait: WaitRecorder) -> None:
    # e.g. the caster rejected the credentials (401) on the second attempt
    source = PolicyInput(
        fail_times=3,
        policy=ReconnectPolicy(initial_delay=10.0, max_delay=120.0, multiplier=2.0),
        persistent_failures=frozenset({2}),
    )

    _reconnect(source, wait)

    assert wait.delays == [10.0, 120.0, 120.0]


class RaisingInput(FakeInput):
    """A fake input whose failing connect() calls raise instead of returning False."""

    def connect(self) -> bool:
        if self.connect_calls < self.fail_times:
            self.connect_calls += 1
            raise OSError("connection refused")
        return super().connect()


def test_a_connect_that_raises_counts_as_one_attempt(wait: WaitRecorder) -> None:
    source = RaisingInput(fail_times=2)

    hub = _reconnect(source, wait)

    assert hub.stats.input_reconnect_attempts == source.connect_calls == 3
    assert hub.stats.input_reconnect_successes == 1
    assert wait.delays == [2.0, 4.0]


def test_stopping_during_a_wait_counts_no_further_attempt() -> None:
    source = FakeInput(fail_times=5)
    stop_at_first_wait = StoppingWait()

    hub = _reconnect(source, stop_at_first_wait)

    assert stop_at_first_wait.delays == [2.0]
    assert hub.stats.input_reconnect_attempts == source.connect_calls == 1
    assert hub.stats.input_reconnect_successes == 0
