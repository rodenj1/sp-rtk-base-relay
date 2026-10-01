"""Shared NTRIP protocol handling, used by NtripDestination and the NTRIP client input."""

from sp_rtk_base_relay.core.ntrip.connection import open_connection
from sp_rtk_base_relay.core.ntrip.protocol import (
    MAX_REPLY_HEAD_BYTES,
    USER_AGENT,
    CasterReply,
    NtripOutcome,
    NtripVersion,
    get_request,
    parse_reply,
    post_request,
    read_reply,
    source_request,
)

__all__ = [
    "MAX_REPLY_HEAD_BYTES",
    "USER_AGENT",
    "CasterReply",
    "NtripOutcome",
    "NtripVersion",
    "get_request",
    "open_connection",
    "parse_reply",
    "post_request",
    "read_reply",
    "source_request",
]
