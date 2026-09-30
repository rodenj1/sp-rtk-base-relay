"""Frame subscribers, tested through the RelayEngine interface (ADR 0003).

An embedding application subscribes to the Frames the Relay reads from
its input.  These tests drive a real engine and hub with a fake input
source and recording destinations, feed raw input bytes, and assert on
what subscribers and destinations observe.
"""

from __future__ import annotations

import queue
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

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
from sp_rtk_base_relay.rtcm_decoder import RTCMMessageDecoder

# ============================================================================
# Test doubles
# ============================================================================


class FeedableInputSource(InputSource):
    """Fake input whose reads return whatever the test feeds it."""

    def __init__(self) -> None:
        super().__init__("fake")
        self._connected = False
        self._chunks: queue.Queue[bytes] = queue.Queue()

    def feed(self, *chunks: bytes) -> None:
        for chunk in chunks:
            self._chunks.put(chunk)

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        self._update_connection_stats(True)
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        try:
            return self._chunks.get(timeout=min(timeout or 0.05, 0.05))
        except queue.Empty:
            return None

    def disconnect(self) -> None:
        self._connected = False

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "fake"}


class RecordingDestination(BaseDestination):
    """Destination that records every enqueued item, with no thread."""

    def __init__(self, name: str, filter_config: FilterConfig | None = None) -> None:
        super().__init__(name, "fake", filter_config or FilterConfig.pass_all())
        self.received: list[bytes] = []

    def enqueue(self, data: bytes) -> bool:
        self.received.append(data)
        return True

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


def rtcm_frame(message_id: int, payload_len: int = 20) -> bytes:
    """Build a CRC-valid RTCM 3 frame whose payload starts with *message_id*."""
    payload = bytearray(payload_len)
    payload[0] = (message_id >> 4) & 0xFF
    payload[1] = (message_id & 0x0F) << 4
    body = bytes([0xD3, (payload_len >> 8) & 0x03, payload_len & 0xFF]) + bytes(payload)
    crc = RTCMMessageDecoder.calc_crc24q(body)
    return body + bytes([(crc >> 16) & 0xFF, (crc >> 8) & 0xFF, crc & 0xFF])


def _dest_config(name: str) -> DestinationConfig:
    return DestinationConfig(
        name=name,
        type="tcp_server",
        enabled=True,
        filter=DestinationFilterConfig(mode="pass_all"),
        config=TcpServerDestinationConfig(host="127.0.0.1", port=5016),
    )


class Rig:
    """A running engine wired to a feedable input and recording destinations."""

    def __init__(self, destinations: list[RecordingDestination]) -> None:
        self.input = FeedableInputSource()
        self.destinations = destinations
        self.engine = RelayEngine(
            InputConfig(source="tcp", config={"host": "x", "port": 1})
        )
        self.restart()

    def restart(self) -> None:
        """(Re)start the engine on the same input and destinations."""
        by_name = {d.name: d for d in self.destinations}

        def create(cfg: DestinationConfig) -> BaseDestination:
            return by_name[cfg.name]

        with (
            patch(
                "sp_rtk_base_relay.engine.InputSourceFactory.create_input_source",
                return_value=self.input,
            ),
            patch(
                "sp_rtk_base_relay.engine.DestinationFactory.create",
                side_effect=create,
            ),
        ):
            self.engine.start([_dest_config(d.name) for d in self.destinations])

    def feed(self, *chunks: bytes) -> None:
        self.input.feed(*chunks)

    def settle(self) -> None:
        """Wait until the hub has consumed everything fed so far."""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self.input._chunks.empty():  # pyright: ignore[reportPrivateUsage]
                time.sleep(0.15)
                return
            time.sleep(0.01)
        raise AssertionError("input never drained")


@pytest.fixture
def rig() -> Iterator[Rig]:
    r = Rig([RecordingDestination("rover")])
    yield r
    r.engine.stop()


def _collect(sub: Any, n: int, timeout: float = 2.0) -> list[Any]:
    got: list[Any] = []
    deadline = time.monotonic() + timeout
    while len(got) < n and time.monotonic() < deadline:
        frame = sub.get_frame(timeout=0.1)
        if frame is not None:
            got.append(frame)
    return got


# ============================================================================
# Behaviour
# ============================================================================


def test_subscriber_receives_each_input_frame_with_its_message_id(rig: Rig) -> None:
    sub = rig.engine.subscribe_frames()
    f1074, f1005 = rtcm_frame(1074), rtcm_frame(1005, 19)

    rig.feed(f1074 + f1005)

    got = _collect(sub, 2)
    assert [(f.message_id, f.data) for f in got] == [(1074, f1074), (1005, f1005)]


def test_frames_split_across_reads_arrive_whole_and_corrupt_frames_never_do(
    rig: Rig,
) -> None:
    sub = rig.engine.subscribe_frames()
    good1, good2 = rtcm_frame(1084, 30), rtcm_frame(1094, 25)
    corrupt = bytearray(rtcm_frame(1124, 22))
    corrupt[10] ^= 0xFF  # payload damaged, CRC no longer matches
    stream = good1 + bytes(corrupt) + good2

    rig.feed(stream[:7], stream[7:40], stream[40:])

    got = _collect(sub, 2)
    assert [(f.message_id, f.data) for f in got] == [(1084, good1), (1094, good2)]
    assert sub.get_frame(timeout=0.3) is None


def test_message_id_filter_delivers_only_requested_frames(rig: Rig) -> None:
    sub = rig.engine.subscribe_frames({1074, 1094})

    rig.feed(
        rtcm_frame(1005, 19) + rtcm_frame(1074) + rtcm_frame(1230, 8) + rtcm_frame(1094)
    )

    got = _collect(sub, 2)
    assert [f.message_id for f in got] == [1074, 1094]
    assert sub.get_frame(timeout=0.3) is None


def test_destination_blocklist_does_not_hide_frames_from_subscribers() -> None:
    blocked = RecordingDestination("ntrip", FilterConfig.blocklist({1074}))
    r = Rig([blocked])
    try:
        sub = r.engine.subscribe_frames()
        f1074, f1005 = rtcm_frame(1074), rtcm_frame(1005, 19)

        r.feed(f1074 + f1005)

        assert [f.message_id for f in _collect(sub, 2)] == [1074, 1005]
        r.settle()
        assert blocked.received == [f1005]
    finally:
        r.engine.stop()


def test_pass_all_destinations_receive_the_input_unchanged_when_subscribed(
    rig: Rig,
) -> None:
    sub = rig.engine.subscribe_frames()
    stream = b"\x00junk" + rtcm_frame(1074) + rtcm_frame(1005, 19) + b"\xd3\x00"
    chunks = [stream[:9], stream[9:31], stream[31:]]

    rig.feed(*chunks)

    assert [f.message_id for f in _collect(sub, 2)] == [1074, 1005]
    rig.settle()
    assert rig.destinations[0].received == chunks


def test_a_subscriber_that_never_reads_drops_frames_without_blocking_destinations(
    rig: Rig,
) -> None:
    rig.engine.subscribe_frames()  # never read
    frames = [rtcm_frame(1074) for _ in range(150)]

    rig.feed(*frames)
    rig.settle()

    status = rig.engine.get_status()
    assert status.frame_subscriber_count == 1
    assert status.frame_subscriber_drops == 50  # queue holds 100
    assert rig.destinations[0].received == frames


def test_subscribing_while_stopped_raises() -> None:
    from sp_rtk_base_relay.exceptions import ServiceError

    engine = RelayEngine(InputConfig(source="tcp", config={"host": "x", "port": 1}))
    with pytest.raises(ServiceError):
        engine.subscribe_frames()


def test_stopping_the_engine_ends_the_subscription_after_buffered_frames() -> None:
    r = Rig([RecordingDestination("rover")])
    sub = r.engine.subscribe_frames()
    r.feed(rtcm_frame(1074), rtcm_frame(1084))
    r.settle()

    r.engine.stop()

    assert sub.closed
    assert [f.message_id for f in _collect(sub, 2)] == [1074, 1084]
    assert sub.get_frame(timeout=0.2) is None
    assert r.engine.get_destination_names() == []


def test_a_restarted_engine_needs_a_new_subscription() -> None:
    r = Rig([RecordingDestination("rover")])
    old = r.engine.subscribe_frames()
    r.engine.stop()
    r.restart()
    try:
        new = r.engine.subscribe_frames()
        r.feed(rtcm_frame(1094))

        assert [f.message_id for f in _collect(new, 1)] == [1094]
        assert old.closed and old.get_frame(timeout=0.2) is None
    finally:
        r.engine.stop()


def test_subscribers_are_independent_and_close_detaches_one(rig: Rig) -> None:
    msm = rig.engine.subscribe_frames({1074})
    everything = rig.engine.subscribe_frames()

    rig.feed(rtcm_frame(1005, 19) + rtcm_frame(1074))
    assert [f.message_id for f in _collect(msm, 1)] == [1074]
    assert [f.message_id for f in _collect(everything, 2)] == [1005, 1074]

    msm.close()
    msm.close()  # idempotent
    assert rig.engine.get_status().frame_subscriber_count == 1

    rig.feed(rtcm_frame(1074))
    assert [f.message_id for f in _collect(everything, 1)] == [1074]
    assert msm.get_frame(timeout=0.2) is None


def test_subscribers_are_never_destinations(rig: Rig) -> None:
    rig.engine.subscribe_frames()

    status = rig.engine.get_status()
    assert rig.engine.get_destination_names() == ["rover"]
    assert status.total_destination_count == 1
    assert [d.name for d in status.destinations] == ["rover"]


def test_a_subscription_can_be_drained_and_iterated(rig: Rig) -> None:
    sub = rig.engine.subscribe_frames()
    rig.feed(rtcm_frame(1005, 19) + rtcm_frame(1074) + rtcm_frame(1084))
    rig.settle()

    first = sub.drain(max_frames=2)
    assert [f.message_id for f in first] == [1005, 1074]

    rig.engine.stop()
    assert [f.message_id for f in sub] == [1084]  # iteration ends once closed


def test_the_hub_only_frames_the_stream_while_a_subscriber_needs_it(rig: Rig) -> None:
    rig.feed(rtcm_frame(1074))
    rig.settle()
    assert rig.engine.get_status().frames_parsed == 0  # pass-all fast path

    sub = rig.engine.subscribe_frames()
    rig.feed(rtcm_frame(1074))
    rig.settle()
    assert rig.engine.get_status().frames_parsed == 1

    sub.close()
    rig.feed(rtcm_frame(1074))
    rig.settle()
    assert rig.engine.get_status().frames_parsed == 1  # back on the fast path


def test_subscribing_while_the_engine_is_stopping_is_refused(rig: Rig) -> None:
    from sp_rtk_base_relay.exceptions import ServiceError

    # The window inside engine.stop(): the hub has stopped (and closed its
    # subscriptions) but the engine has not yet marked itself stopped.
    rig.engine._hub.stop()  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]

    with pytest.raises(ServiceError):
        rig.engine.subscribe_frames()
    assert rig.engine.get_status().frame_subscriber_count == 0
