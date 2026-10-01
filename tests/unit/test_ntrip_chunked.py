"""Tests for the shared streaming decoder of NTRIP v2 chunked bodies.

Seam under test: ChunkedDecoder.feed(), bytes as they arrive off the socket in,
decoded body bytes out.
"""

import pytest

from sp_rtk_base_relay.core.ntrip import ChunkedDecoder

RTCM = bytes.fromhex("d300133ed00000000000000000000000000000000000f24bf4")


def _chunk(data: bytes) -> bytes:
    return f"{len(data):x}\r\n".encode() + data + b"\r\n"


def _feed_in_pieces(stream: bytes, size: int) -> bytes:
    decoder = ChunkedDecoder()
    return b"".join(
        decoder.feed(stream[i : i + size]) for i in range(0, len(stream), size)
    )


def test_whole_chunks_decode_to_their_data() -> None:
    assert ChunkedDecoder().feed(_chunk(RTCM) + _chunk(RTCM)) == RTCM + RTCM


@pytest.mark.parametrize("size", [1, 2, 3, 7, 25])
def test_chunks_split_anywhere_decode_the_same(size: int) -> None:
    stream = _chunk(RTCM) + _chunk(RTCM[:5]) + _chunk(RTCM[5:])

    assert _feed_in_pieces(stream, size) == RTCM + RTCM


def test_chunk_extensions_are_ignored() -> None:
    stream = f"{len(RTCM):x};name=value\r\n".encode() + RTCM + b"\r\n"

    assert ChunkedDecoder().feed(stream) == RTCM


def test_the_last_chunk_ends_the_body() -> None:
    decoder = ChunkedDecoder()

    assert decoder.feed(_chunk(RTCM) + b"0\r\n\r\n" + _chunk(RTCM)) == RTCM
    assert decoder.finished
    assert decoder.feed(_chunk(RTCM)) == b""


@pytest.mark.parametrize(
    "stream",
    [
        b"zz\r\n" + RTCM,  # not a hex size
        _chunk(RTCM)[:-2] + b"XX",  # data not followed by CRLF
        b"1" * 300,  # a size line that never ends
    ],
)
def test_a_malformed_body_is_an_error(stream: bytes) -> None:
    with pytest.raises(ValueError):
        ChunkedDecoder().feed(stream)
