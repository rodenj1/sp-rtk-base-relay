"""Tests for the NTRIP client input running inside the Relay.

Seams under test, both against a scripted fake caster on a real localhost
socket:
- RelayEngine started with an `ntrip` InputConfig: Frames from the caster
  reach subscribe_frames(), and a refused first connect fails start().
- A real BroadcastHub with an NtripInputSource and an injected reconnect wait
  that records each delay: persistent failures back off to the maximum, and a
  data timeout triggers a reconnect.
"""

import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import patch

import pytest

from sp_rtk_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    InputConfig,
    NtripInputConfig,
    TcpServerDestinationConfig,
)
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
from sp_rtk_base_relay.core.input_sources.ntrip_input import NtripInputSource
from sp_rtk_base_relay.core.message_filter import FilterConfig
from sp_rtk_base_relay.engine import RelayEngine
from sp_rtk_base_relay.exceptions import NtripConnectionError
from tests.fixtures.scripted_ntrip_caster import FakeCaster, Script

RTCM_1005 = bytes.fromhex("d300133ed00000000000000000000000000000000000f24bf4")


def _chunk(data: bytes) -> bytes:
    return f"{len(data):x}\r\n".encode() + data + b"\r\n"


@pytest.fixture
def caster() -> Iterator[FakeCaster]:
    fake = FakeCaster()
    yield fake
    fake.close()


def _ntrip_config(caster: FakeCaster, **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "caster": "127.0.0.1",
        "port": caster.port,
        "mountpoint": "MP1",
        "username": "rover",
        "password": "roverpw",
        "connection_timeout": 2.0,
    }
    config.update(overrides)
    return config


class RecordingDestination(BaseDestination):
    """A destination that records what the hub hands it, without a thread."""

    def __init__(self, filter_config: FilterConfig) -> None:
        super().__init__("recorder", "fake", filter_config)
        self.received: list[bytes] = []

    def enqueue(self, data: bytes) -> bool:
        self.received.append(data)
        return True

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
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


def _any_destination_config() -> DestinationConfig:
    return DestinationConfig(
        name="recorder",
        type="tcp_server",
        enabled=True,
        filter=DestinationFilterConfig(mode="pass_all"),
        config=TcpServerDestinationConfig(host="127.0.0.1", port=5016),
    )


def _wait_for(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition never became true"
        time.sleep(0.01)


class TestEngine:
    @pytest.mark.parametrize(
        ("version", "reply", "body"),
        [
            ("1.0", b"ICY 200 OK\r\n", [RTCM_1005] * 5),
            (
                "2.0",
                b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n",
                [_chunk(RTCM_1005)] * 5,
            ),
        ],
    )
    def test_frames_from_the_caster_reach_subscribers(
        self, caster: FakeCaster, version: str, reply: bytes, body: list[bytes]
    ) -> None:
        caster.scripts.append(Script(reply=reply, body=body))
        engine = RelayEngine(
            InputConfig(source="ntrip", config=_ntrip_config(caster, version=version))
        )
        engine.start([])
        try:
            frames = engine.subscribe_frames()
            frame = frames.get_frame(timeout=3.0)
            assert frame is not None
            assert (frame.message_id, frame.data) == (1005, RTCM_1005)
            assert engine.get_status().input.connected
        finally:
            engine.stop()

    @pytest.mark.parametrize(
        "reply",
        [
            b"ICY 200 OK\r\n" + RTCM_1005 * 3,  # data in the same packet
            b"ICY 200 OK\r\nServer: NTRIP Caster\r\n\r\n" + RTCM_1005 * 3,
            b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n\r\n" + RTCM_1005 * 3,
        ],
    )
    def test_bytes_arriving_with_the_reply_become_frames(
        self, caster: FakeCaster, reply: bytes
    ) -> None:
        # Frames that arrive with the reply reach the hub as soon as start()
        # returns, before a subscribe_frames() call could; a destination given
        # to start() sees them. Its allowlist makes the hub cut whole Frames.
        caster.scripts.append(Script(reply=reply))
        recorder = RecordingDestination(FilterConfig.allowlist({1005}))
        with patch("sp_rtk_base_relay.engine.DestinationFactory") as factory:
            factory.create.return_value = recorder
            engine = RelayEngine(
                InputConfig(source="ntrip", config=_ntrip_config(caster))
            )
            engine.start([_any_destination_config()])
        try:
            _wait_for(lambda: len(recorder.received) >= 3)
            assert recorder.received == [RTCM_1005] * 3
        finally:
            engine.stop()

    def test_a_refused_first_connect_fails_start(self, caster: FakeCaster) -> None:
        caster.scripts.append(
            Script(reply=b"HTTP/1.1 401 Unauthorized\r\n\r\n", hold=False)
        )
        engine = RelayEngine(InputConfig(source="ntrip", config=_ntrip_config(caster)))

        with pytest.raises(NtripConnectionError):
            engine.start([])
        assert not engine.is_running


class WaitRecorder:
    """Stands in for the hub's reconnect wait: records each delay, never sleeps."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, timeout: float) -> bool:
        self.delays.append(timeout)
        return False


@pytest.fixture
def make_hub() -> Iterator[Callable[[NtripInputSource, WaitRecorder], BroadcastHub]]:
    hubs: list[BroadcastHub] = []

    def _make(source: NtripInputSource, wait: WaitRecorder) -> BroadcastHub:
        hub = BroadcastHub(source, [], reconnect_wait=wait)
        hubs.append(hub)
        return hub

    yield _make
    for hub in hubs:
        hub.stop()


class TestHub:
    @pytest.mark.parametrize(
        ("rejection", "delays"),
        [
            (b"HTTP/1.1 401 Unauthorized\r\n\r\n", [120.0, 120.0]),  # persistent
            (b"HTTP/1.1 404 Not Found\r\n\r\n", [120.0, 120.0]),  # persistent
            (b"SOURCETABLE 200 OK\r\n\r\nENDSOURCETABLE\r\n", [120.0, 120.0]),
            (b"HTTP/1.1 403 Forbidden\r\n\r\n", [120.0, 120.0]),
            (b"<html>Down for maintenance</html>\r\n", [10.0, 20.0]),  # worth retrying
        ],
    )
    def test_persistent_failures_back_off_to_the_maximum(
        self,
        caster: FakeCaster,
        make_hub: Callable[[NtripInputSource, WaitRecorder], BroadcastHub],
        rejection: bytes,
        delays: list[float],
    ) -> None:
        caster.scripts += [
            Script(
                reply=b"ICY 200 OK\r\n" + RTCM_1005, hold=False
            ),  # then the stream ends
            Script(reply=rejection, hold=False),
            Script(reply=rejection, hold=False),
            Script(reply=b"ICY 200 OK\r\n"),
        ]
        source = NtripInputSource(NtripInputConfig(**_ntrip_config(caster)))
        wait = WaitRecorder()
        hub = make_hub(source, wait)

        hub.start()
        _wait_for(lambda: hub.stats.input_reconnect_successes == 1)

        assert wait.delays == delays
        assert len(caster.requests) == 4

    def test_a_data_timeout_triggers_a_reconnect(
        self,
        caster: FakeCaster,
        make_hub: Callable[[NtripInputSource, WaitRecorder], BroadcastHub],
    ) -> None:
        caster.scripts += [
            Script(reply=b"ICY 200 OK\r\n"),  # accepted, then silence
            Script(reply=b"ICY 200 OK\r\n", body=[RTCM_1005] * 20),
        ]
        source = NtripInputSource(
            NtripInputConfig(**_ntrip_config(caster, data_timeout=0.3))
        )
        hub = make_hub(source, WaitRecorder())

        hub.start()
        _wait_for(lambda: hub.stats.input_reconnect_successes == 1)

        assert len(caster.requests) == 2
        assert hub.stats.input_connection_failures == {"data_timeout": 1}
        _wait_for(lambda: hub.stats.bytes_received >= len(RTCM_1005))
