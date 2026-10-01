"""NTRIP request building and caster reply parsing."""

from __future__ import annotations

import base64
import re
import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from sp_rtk_base_relay import __version__
from sp_rtk_base_relay.exceptions import NtripConnectionError, NtripFailure

USER_AGENT = f"NTRIP sp-rtk-base-relay/{__version__}"

NtripVersion = Literal["1.0", "2.0"]

# A caster's reply head is a status line plus a few headers; anything longer isn't one.
MAX_REPLY_HEAD_BYTES = 16 * 1024


class NtripOutcome(str, Enum):
    """How a caster answered an NTRIP request."""

    ACCEPTED = "accepted"
    SOURCETABLE = "sourcetable"
    AUTH_REJECTED = "auth_rejected"
    NOT_FOUND = "not_found"
    BAD_REPLY = "bad_reply"


# v1 server errors (BKG ntripcaster wording), matched case-insensitively.
_V1_ERRORS = {
    "error - bad password": NtripOutcome.AUTH_REJECTED,
    "error - mount point taken or invalid": NtripOutcome.NOT_FOUND,
}

_FAILURE_REASONS = {
    NtripOutcome.SOURCETABLE: NtripFailure.MOUNTPOINT,
    NtripOutcome.NOT_FOUND: NtripFailure.MOUNTPOINT,
    NtripOutcome.AUTH_REJECTED: NtripFailure.AUTH,
    NtripOutcome.BAD_REPLY: NtripFailure.CASTER,
}

# Content types that mark a v2 200 reply as a sourcetable. text/plain is what
# 2RTKNTRIP sent before 2.3.0; no caster sends correction data as text/plain.
_SOURCETABLE_TYPES = ("gnss/sourcetable", "text/plain")

# One complete header line ("Name: value"), or the blank line ending a header block.
_HEADER_LINE = re.compile(rb"(?:[!#$%&'*+.^_`|~0-9A-Za-z-]+:[^\r\n]*)?\r?\n")


@dataclass(frozen=True)
class CasterReply:
    """A caster's parsed reply, plus any bytes that arrived after its headers."""

    outcome: NtripOutcome
    status_line: str
    leftover: bytes
    headers: dict[str, str] = field(default_factory=dict[str, str])

    @property
    def failure_reason(self) -> NtripFailure | None:
        """Why the request failed, or ``None`` if the caster accepted it."""
        return _FAILURE_REASONS.get(self.outcome)


def source_request(mountpoint: str, password: str) -> bytes:
    """An NTRIP v1.0 server's ``SOURCE`` request."""
    return (
        f"SOURCE {password} /{mountpoint}\r\nSource-Agent: {USER_AGENT}\r\n\r\n"
    ).encode("ascii")


def post_request(host: str, mountpoint: str, username: str, password: str) -> bytes:
    """An NTRIP v2.0 server's ``POST`` request, announcing a chunked upload."""
    return _http_request(
        f"POST /{mountpoint} HTTP/1.1",
        [
            ("Host", host),
            ("Ntrip-Version", "Ntrip/2.0"),
            ("Authorization", _basic_auth(username, password)),
            ("User-Agent", USER_AGENT),
            ("Transfer-Encoding", "chunked"),
        ],
    )


def get_request(
    host: str,
    mountpoint: str,
    version: NtripVersion,
    username: str = "",
    password: str = "",
    extra_headers: Sequence[tuple[str, str]] = (),
) -> bytes:
    """An NTRIP client's ``GET`` request for a mountpoint.

    Always sends ``Host``, in v1 too. Sends no ``Authorization`` without a
    username, for anonymous casters. ``extra_headers`` go last (e.g. v2's
    ``Ntrip-GGA``).
    """
    if version == "1.0":
        request_line = f"GET /{mountpoint} HTTP/1.0"
        headers = [("Host", host)]
    else:
        request_line = f"GET /{mountpoint} HTTP/1.1"
        headers = [("Host", host), ("Ntrip-Version", "Ntrip/2.0")]
    headers.append(("User-Agent", USER_AGENT))
    if username:
        headers.append(("Authorization", _basic_auth(username, password)))
    headers.extend(extra_headers)
    return _http_request(request_line, headers)


def _http_request(request_line: str, headers: Sequence[tuple[str, str]]) -> bytes:
    lines = [request_line, *(f"{name}: {value}" for name, value in headers), "", ""]
    return "\r\n".join(lines).encode("ascii")


def _basic_auth(username: str, password: str) -> str:
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {credentials}"


def read_reply(sock: socket.socket, timeout: float) -> CasterReply:
    """Read a caster's reply to a request and parse it.

    Reads until the status line has arrived and, for an HTTP reply, its whole
    header block. A v1 reply is returned as soon as its status line is in, since
    v1 has no reliable end of headers. Bytes that arrived after the headers are
    kept in :attr:`CasterReply.leftover`. The socket's timeout is restored.

    Raises:
        NtripConnectionError: ``CASTER``, if no status line arrives in time.
    """
    original_timeout = sock.gettimeout()
    deadline = time.monotonic() + timeout
    buf = b""
    try:
        while not _reply_head_complete(buf) and len(buf) <= MAX_REPLY_HEAD_BYTES:
            sock.settimeout(max(deadline - time.monotonic(), 0.001))
            try:
                chunk = sock.recv(4096)
            except TimeoutError as e:
                if b"\n" in buf:
                    break  # a status line arrived; parse what came with it
                raise NtripConnectionError(
                    f"NTRIP reply timeout after {timeout}s", reason=NtripFailure.CASTER
                ) from e
            if not chunk:
                break
            buf += chunk
    finally:
        sock.settimeout(original_timeout)
    reply = parse_reply(buf)
    if len(buf) > MAX_REPLY_HEAD_BYTES and not _reply_head_complete(buf):
        return CasterReply(NtripOutcome.BAD_REPLY, reply.status_line, b"")
    return reply


def _reply_head_complete(buf: bytes) -> bool:
    status, newline, rest = buf.partition(b"\n")
    if not newline:
        return False
    if not status.startswith(b"HTTP/"):
        return True
    return _split_header_block(rest)[2]


def parse_reply(data: bytes) -> CasterReply:
    """Parse the start of a caster's reply."""
    status, _, rest = data.partition(b"\n")
    status_line = status.rstrip(b"\r").decode("ascii", errors="replace").strip()
    head, leftover, _ = _split_header_block(rest)
    headers = _parse_headers(head)
    outcome = _classify_status(status_line)
    if outcome is NtripOutcome.ACCEPTED and _is_sourcetable_type(headers):
        outcome = NtripOutcome.SOURCETABLE
    return CasterReply(
        outcome=outcome,
        status_line=status_line,
        leftover=leftover,
        headers=headers,
    )


def _split_header_block(data: bytes) -> tuple[bytes, bytes, bool]:
    """Split the header lines after a status line from the data that follows.

    Takes complete header lines up to and including a blank line, and says whether
    that blank line was seen. v1 replies often have no headers at all, and their
    data (RTCM, starting 0xD3) never looks like a header line, so it is left over
    intact.
    """
    pos = 0
    while match := _HEADER_LINE.match(data, pos):
        pos = match.end()
        if match.group().strip() == b"":
            return data[:pos], data[pos:], True
    return data[:pos], data[pos:], False


def _parse_headers(head: bytes) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in head.decode("ascii", errors="replace").splitlines():
        name, sep, value = line.partition(":")
        if sep:
            headers[name.strip().lower()] = value.strip()
    return headers


def _is_sourcetable_type(headers: dict[str, str]) -> bool:
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    return content_type in _SOURCETABLE_TYPES


def _status_code(status_line: str) -> int | None:
    """The numeric code of an ``ICY``/``HTTP/1.x``/``SOURCETABLE`` status line."""
    parts = status_line.split()
    if len(parts) < 2 or not (
        parts[0] in ("ICY", "SOURCETABLE") or parts[0].startswith("HTTP/1.")
    ):
        return None
    return int(parts[1]) if parts[1].isdigit() else None


def _classify_status(status_line: str) -> NtripOutcome:
    if status_line == "OK":  # BKG reference caster's v1 server reply
        return NtripOutcome.ACCEPTED
    if status_line.lower() in _V1_ERRORS:
        return _V1_ERRORS[status_line.lower()]
    code = _status_code(status_line)
    if code == 200:
        if status_line.startswith("SOURCETABLE"):
            return NtripOutcome.SOURCETABLE
        return NtripOutcome.ACCEPTED
    if code in (401, 403):
        return NtripOutcome.AUTH_REJECTED
    if code == 404:
        return NtripOutcome.NOT_FOUND
    return NtripOutcome.BAD_REPLY
