"""Streaming decoder for NTRIP v2 (HTTP/1.1) chunked bodies."""

from __future__ import annotations

# A chunk-size line is a few hex digits plus optional extensions; anything this
# long isn't one.
_MAX_SIZE_LINE = 256


class ChunkedDecoder:
    """Decodes a ``Transfer-Encoding: chunked`` body as it arrives.

    Feed it bytes in whatever pieces the socket delivers; it returns the body
    bytes decoded so far and keeps any partial chunk header for the next call.
    """

    def __init__(self) -> None:
        self._buffer = b""
        self._remaining = 0  # data bytes left in the current chunk
        self._expect_crlf = False  # the CRLF after a chunk's data is due
        self._finished = False  # the last (zero-size) chunk has been seen

    @property
    def finished(self) -> bool:
        """Whether the body has ended (the caster sent its last chunk)."""
        return self._finished

    def feed(self, data: bytes) -> bytes:
        """Decode the next bytes of the body.

        Raises:
            ValueError: If the bytes aren't a valid chunked body.
        """
        if self._finished:
            return b""
        self._buffer += data
        out = bytearray()
        while self._buffer:
            if self._remaining:
                taken = self._buffer[: self._remaining]
                out += taken
                self._buffer = self._buffer[len(taken) :]
                self._remaining -= len(taken)
                if not self._remaining:
                    self._expect_crlf = True
            elif self._expect_crlf:
                if len(self._buffer) < 2 and self._buffer != b"\n":
                    break
                if self._buffer.startswith(b"\r\n"):
                    self._buffer = self._buffer[2:]
                elif self._buffer.startswith(b"\n"):
                    self._buffer = self._buffer[1:]
                else:
                    raise ValueError("chunk data not followed by CRLF")
                self._expect_crlf = False
            else:
                line, newline, rest = self._buffer.partition(b"\n")
                if not newline:
                    if len(self._buffer) > _MAX_SIZE_LINE:
                        raise ValueError("chunk size line too long")
                    break
                self._buffer = rest
                size_field = line.split(b";", 1)[0].strip()
                try:
                    size = int(size_field, 16)
                except ValueError:
                    raise ValueError(f"bad chunk size {size_field!r}") from None
                if size < 0:
                    raise ValueError(f"bad chunk size {size_field!r}")
                if size == 0:
                    self._finished = True
                    self._buffer = b""
                    break
                self._remaining = size
        return bytes(out)
