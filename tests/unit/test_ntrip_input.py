"""Tests for the NTRIP client input source.

Seam under test: NtripInputSource's public interface (connect(), read_data(),
disconnect(), reconnect_policy, last_failure_persistent), against a scripted
fake caster listening on a real localhost socket.
"""

import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from sp_rtk_base_relay.config import NtripInputConfig
from sp_rtk_base_relay.core.input_sources.base_input import ReconnectPolicy
from sp_rtk_base_relay.core.input_sources.ntrip_input import NtripInputSource
from sp_rtk_base_relay.exceptions import (
    ConnectFailure,
    NtripConnectionError,
    NtripFailure,
)
from tests.fixtures.scripted_ntrip_caster import FakeCaster, Script

RTCM = bytes.fromhex("d300133ed00000000000000000000000000000000000f24bf4")


@pytest.fixture
def caster() -> Iterator[FakeCaster]:
    fake = FakeCaster()
    yield fake
    fake.close()


def _source(caster: FakeCaster, **overrides: Any) -> NtripInputSource:
    config: dict[str, Any] = {
        "caster": "127.0.0.1",
        "port": caster.port,
        "mountpoint": "MP1",
        "username": "rover",
        "password": "roverpw",
        "connection_timeout": 2.0,
    }
    config.update(overrides)
    return NtripInputSource(NtripInputConfig(**config))


def _read(source: NtripInputSource, want: int, timeout: float = 2.0) -> bytes:
    """Read until ``want`` bytes have arrived (or time runs out)."""
    data = b""
    deadline = time.monotonic() + timeout
    while len(data) < want and time.monotonic() < deadline:
        data += source.read_data(timeout=0.2) or b""
    return data


@pytest.fixture
def opened() -> Iterator[list[NtripInputSource]]:
    """Sources a test opened, disconnected afterwards."""
    sources: list[NtripInputSource] = []
    yield sources
    for source in sources:
        source.disconnect()


class TestSuccess:
    def test_v1_streams_the_rtcm_after_icy_200(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(Script(reply=b"ICY 200 OK\r\n", body=[RTCM, RTCM]))
        source = _source(caster, version="1.0")
        opened.append(source)

        assert source.connect() is True
        assert source.is_connected
        assert _read(source, 2 * len(RTCM)) == RTCM + RTCM

        request = caster.requests[0]
        assert request.startswith(b"GET /MP1 HTTP/1.0\r\n")
        assert b"\r\nHost: 127.0.0.1\r\n" in request
        assert b"Ntrip-Version" not in request

    def test_v2_streams_an_unchunked_body(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(
            Script(
                reply=b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n\r\n",
                body=[RTCM],
            )
        )
        source = _source(caster, version="2.0")
        opened.append(source)

        assert source.connect() is True
        assert _read(source, len(RTCM)) == RTCM
        assert b"\r\nNtrip-Version: Ntrip/2.0\r\n" in caster.requests[0]

    def test_a_chunked_v2_body_is_decoded(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        def chunk(data: bytes) -> bytes:
            return f"{len(data):x}\r\n".encode() + data + b"\r\n"

        stream = chunk(RTCM) + chunk(RTCM[:7]) + chunk(RTCM[7:])
        caster.scripts.append(
            Script(
                # the first chunk arrives with the headers; the rest in odd pieces
                reply=b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                + stream[:10],
                body=[stream[10:31], stream[31:]],
            )
        )
        source = _source(caster)
        opened.append(source)

        assert source.connect() is True
        assert _read(source, 2 * len(RTCM)) == RTCM + RTCM


class TestRejections:
    @pytest.mark.parametrize(
        ("reply", "reason"),
        [
            # an unknown or offline mountpoint
            (
                b"SOURCETABLE 200 OK\r\n\r\nSTR;OTHER;;\r\nENDSOURCETABLE\r\n",
                NtripFailure.MOUNTPOINT,
            ),
            (
                b"HTTP/1.1 200 OK\r\nContent-Type: gnss/sourcetable\r\n\r\nENDSOURCETABLE\r\n",
                NtripFailure.MOUNTPOINT,
            ),
            (b"HTTP/1.1 404 Not Found\r\n\r\n", NtripFailure.MOUNTPOINT),
            # credentials
            (b"HTTP/1.0 401 Unauthorized\r\n\r\n", NtripFailure.AUTH),
            (b"HTTP/1.1 401 Unauthorized\r\n\r\n", NtripFailure.AUTH),
        ],
    )
    def test_a_persistent_rejection_raises_its_reason(
        self, caster: FakeCaster, reply: bytes, reason: NtripFailure
    ) -> None:
        caster.scripts.append(Script(reply=reply, hold=False))
        source = _source(caster)

        with pytest.raises(NtripConnectionError) as raised:
            source.connect()

        assert raised.value.reason is reason
        assert source.last_failure_persistent
        assert not source.is_connected

    def test_a_garbage_reply_is_a_caster_failure_worth_retrying(
        self, caster: FakeCaster
    ) -> None:
        caster.scripts.append(Script(reply=b"<html>Banned</html>\r\n", hold=False))
        source = _source(caster)

        with pytest.raises(NtripConnectionError) as raised:
            source.connect()

        assert raised.value.reason is NtripFailure.CASTER
        assert not source.last_failure_persistent
        assert not source.is_connected

    def test_a_success_after_a_persistent_failure_clears_it(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts += [
            Script(reply=b"HTTP/1.1 401 Unauthorized\r\n\r\n", hold=False),
            Script(reply=b"ICY 200 OK\r\n"),
        ]
        source = _source(caster)
        opened.append(source)
        with pytest.raises(NtripConnectionError):
            source.connect()

        assert source.connect() is True
        assert not source.last_failure_persistent


class TestRequests:
    def test_an_anonymous_caster_gets_no_credentials(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(Script(reply=b"ICY 200 OK\r\n"))
        source = _source(caster, username="", password="")
        opened.append(source)

        assert source.connect() is True
        assert b"Authorization" not in caster.requests[0]

    def test_credentials_are_sent_as_basic_auth(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(Script(reply=b"ICY 200 OK\r\n"))
        source = _source(caster)
        opened.append(source)

        source.connect()

        # base64("rover:roverpw")
        assert (
            b"\r\nAuthorization: Basic cm92ZXI6cm92ZXJwdw==\r\n" in caster.requests[0]
        )


class TestConnectionFailures:
    def test_a_tls_handshake_failure_is_a_connect_failure(
        self, caster: FakeCaster
    ) -> None:
        # a plain NTRIP caster answers the TLS hello with its own bytes
        caster.scripts.append(Script(greeting=b"ICY 200 OK\r\n\r\n"))
        source = _source(caster, tls=True)

        with pytest.raises(NtripConnectionError) as raised:
            source.connect()

        assert raised.value.reason is NtripFailure.CONNECT
        assert raised.value.connect_failure is ConnectFailure.TLS_HANDSHAKE
        assert not source.last_failure_persistent
        assert not source.is_connected

    def test_the_inputs_reconnect_policy_comes_from_its_config(
        self, caster: FakeCaster
    ) -> None:
        source = _source(
            caster, retry_initial_delay=5, retry_max_delay=300, retry_multiplier=3.0
        )

        assert source.reconnect_policy == ReconnectPolicy(5, 300, 3.0)


class TestLosingTheStream:
    def test_no_data_for_the_data_timeout_drops_the_connection(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(Script(reply=b"ICY 200 OK\r\n" + RTCM))  # then silence
        source = _source(caster, data_timeout=0.3)
        opened.append(source)
        source.connect()
        assert source.read_data(timeout=0.1) == RTCM

        start = time.monotonic()
        with pytest.raises(NtripConnectionError) as raised:
            while time.monotonic() - start < 2.0:
                source.read_data(timeout=0.1)

        assert raised.value.reason is NtripFailure.DATA_TIMEOUT
        assert 0.25 <= time.monotonic() - start < 1.0
        assert not source.is_connected

    def test_data_arriving_keeps_the_connection(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(Script(reply=b"ICY 200 OK\r\n", body=[RTCM] * 20))
        source = _source(caster, data_timeout=0.3)
        opened.append(source)
        source.connect()

        assert _read(source, 20 * len(RTCM)) == RTCM * 20  # ~0.4 s, every 0.02 s
        assert source.is_connected

    @pytest.mark.parametrize(
        ("reply", "body"),
        [
            (b"ICY 200 OK\r\n", [RTCM]),
            (
                b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
                [b"19\r\n" + RTCM + b"\r\n0\r\n\r\n"],
            ),
        ],
    )
    def test_the_caster_ending_the_stream_disconnects(
        self,
        caster: FakeCaster,
        opened: list[NtripInputSource],
        reply: bytes,
        body: list[bytes],
    ) -> None:
        caster.scripts.append(Script(reply=reply, body=body, hold=False))
        source = _source(caster)
        opened.append(source)
        source.connect()

        assert _read(source, len(RTCM)) == RTCM
        deadline = time.monotonic() + 2.0
        while source.is_connected and time.monotonic() < deadline:
            source.read_data(timeout=0.1)

        assert not source.is_connected
        assert source.last_error is not None

    def test_a_corrupt_chunked_body_is_a_caster_failure(
        self, caster: FakeCaster, opened: list[NtripInputSource]
    ) -> None:
        caster.scripts.append(
            Script(
                reply=b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",
                body=[b"zz\r\nnot a chunk"],
            )
        )
        source = _source(caster)
        opened.append(source)
        source.connect()

        with pytest.raises(NtripConnectionError) as raised:
            _read(source, 1)

        assert raised.value.reason is NtripFailure.CASTER
        assert not source.is_connected


class TestRobustness:
    def test_a_corrupt_chunked_body_with_the_reply_is_a_caster_failure(
        self, caster: FakeCaster
    ) -> None:
        caster.scripts.append(
            Script(
                reply=b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\nnope"
            )
        )
        source = _source(caster)

        with pytest.raises(NtripConnectionError) as raised:
            source.connect()

        assert raised.value.reason is NtripFailure.CASTER
        assert not source.is_connected

    def test_disconnecting_during_a_slow_connect_leaves_it_disconnected(
        self, caster: FakeCaster
    ) -> None:
        # e.g. the hub stopping while the caster is slow to reply
        caster.scripts.append(Script(delay=0.5, reply=b"ICY 200 OK\r\n" + RTCM))
        source = _source(caster)
        outcome: list[object] = []

        def _connect() -> None:
            try:
                outcome.append(source.connect())
            except NtripConnectionError as error:
                outcome.append(error)

        connecting = threading.Thread(target=_connect)
        connecting.start()
        time.sleep(0.2)
        source.disconnect()
        connecting.join(3)

        assert outcome == [False]
        assert not source.is_connected
        assert source.read_data(timeout=0.1) is None
