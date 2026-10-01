"""Unit tests for the shared NTRIP protocol module (core/ntrip).

Seam under test: the module's public functions, as NtripDestination and the
upcoming NTRIP client input call them: reply parsing (raw caster bytes in,
typed outcome plus leftover bytes out), request building (exact bytes), and
opening a connection against real localhost listeners.
"""

import shutil
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sp_rtk_base_relay import __version__
from sp_rtk_base_relay.core.ntrip import (
    NtripOutcome,
    get_request,
    open_connection,
    parse_reply,
    post_request,
    read_reply,
    source_request,
)
from sp_rtk_base_relay.exceptions import (
    ConnectFailure,
    NtripConnectionError,
    NtripFailure,
)

UA = f"NTRIP sp-rtk-base-relay/{__version__}"

# A valid RTCM 1005 frame, standing in for correction data after a reply.
RTCM = bytes.fromhex("d300133ed00000000000000000000000000000000000f24bf4")


class TestParseReply:
    def test_icy_200_ok_is_accepted_and_keeps_the_data_after_it(self) -> None:
        reply = parse_reply(b"ICY 200 OK\r\n" + RTCM)

        assert reply.outcome is NtripOutcome.ACCEPTED
        assert reply.leftover == RTCM

    @pytest.mark.parametrize(
        ("reply", "outcome"),
        [
            # v1 servers (BKG style) and clients
            (b"ERROR - Bad Password\r\n", NtripOutcome.AUTH_REJECTED),
            (b"ERROR - Mount Point Taken or Invalid\r\n", NtripOutcome.NOT_FOUND),
            (b"HTTP/1.0 401 Unauthorized\r\n\r\n", NtripOutcome.AUTH_REJECTED),
            (b"SOURCETABLE 401 Unauthorized\r\n", NtripOutcome.AUTH_REJECTED),
            # v2
            (b"HTTP/1.1 401 Unauthorized\r\n\r\n", NtripOutcome.AUTH_REJECTED),
            (b"HTTP/1.1 403 Forbidden\r\n\r\n", NtripOutcome.AUTH_REJECTED),
            (b"HTTP/1.1 404 Not Found\r\n\r\n", NtripOutcome.NOT_FOUND),
            (b"HTTP/1.1 400 Missing Host header\r\n\r\n", NtripOutcome.BAD_REPLY),
            (b"HTTP/1.1 500 Internal Server Error\r\n\r\n", NtripOutcome.BAD_REPLY),
            # R4: "200" in the line is not a 200 status
            (
                b"HTTP/1.1 400 Bad request (see RFC 7230 section 200)\r\n\r\n",
                NtripOutcome.BAD_REPLY,
            ),
            (b"ICY 401 Unauthorized 200\r\n", NtripOutcome.AUTH_REJECTED),
            # not NTRIP at all
            (b"<html><body>banned</body></html>\r\n", NtripOutcome.BAD_REPLY),
            (b"ERROR - something unexpected\r\n", NtripOutcome.BAD_REPLY),
            (b"HTTP/1.1 abc\r\n\r\n", NtripOutcome.BAD_REPLY),
            (b"", NtripOutcome.BAD_REPLY),
        ],
    )
    def test_rejections_are_classified_by_their_status(
        self, reply: bytes, outcome: NtripOutcome
    ) -> None:
        assert parse_reply(reply).outcome is outcome

    @pytest.mark.parametrize(
        "reply",
        [
            b"OK\r\n",  # R1: BKG reference caster
            b"ICY 200 OK\r\n",
            b"HTTP/1.0 200 OK\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\nNtrip-Version: Ntrip/2.0\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n\r\n",
        ],
    )
    def test_every_success_form_is_accepted(self, reply: bytes) -> None:  # R1
        parsed = parse_reply(reply + RTCM)

        assert parsed.outcome is NtripOutcome.ACCEPTED
        assert parsed.leftover == RTCM

    def test_v1_headers_after_icy_are_not_left_over(self) -> None:
        parsed = parse_reply(b"ICY 200 OK\r\nConnection: keep-alive\r\n\r\n" + RTCM)

        assert parsed.leftover == RTCM

    def test_v2_headers_are_parsed_and_the_body_left_over(self) -> None:
        parsed = parse_reply(
            b"HTTP/1.1 200 OK\r\nContent-Type: gnss/data\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n19\r\n" + RTCM
        )

        assert parsed.headers["transfer-encoding"] == "chunked"
        assert parsed.leftover == b"19\r\n" + RTCM

    @pytest.mark.parametrize(
        "reply",
        [
            b"SOURCETABLE 200 OK\r\nServer: NTRIP Caster\r\nContent-Type: text/plain\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nNtrip-Version: Ntrip/2.0\r\nContent-Type: gnss/sourcetable\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Type: Gnss/Sourcetable; charset=ascii\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n",  # 2RTKNTRIP before 2.3.0
        ],
    )
    def test_sourcetables_are_recognised(self, reply: bytes) -> None:
        table = b"STR;MP1;MP1;RTCM 3.2;;;;;;0;0;;;N;N;0;\r\nENDSOURCETABLE\r\n"
        parsed = parse_reply(reply + table)

        assert parsed.outcome is NtripOutcome.SOURCETABLE
        assert parsed.leftover == table


@pytest.fixture
def caster_link() -> Iterator[tuple[socket.socket, socket.socket]]:
    """(our end, the caster's end) of a connected socket pair."""
    ours, theirs = socket.socketpair()
    yield ours, theirs
    ours.close()
    theirs.close()


class TestReadReply:
    def test_a_reply_split_across_reads_is_assembled(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link

        def _send_in_pieces() -> None:
            for piece in (
                b"HTTP/1.1 ",
                b"200 OK\r\nContent-Type: gnss/",
                b"data\r\n\r\n" + RTCM,
            ):
                theirs.sendall(piece)
                time.sleep(0.05)

        threading.Thread(target=_send_in_pieces).start()
        reply = read_reply(ours, timeout=2.0)

        assert reply.outcome is NtripOutcome.ACCEPTED
        assert reply.headers["content-type"] == "gnss/data"
        assert reply.leftover == RTCM

    def test_a_head_ending_in_mixed_line_endings_is_complete(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link
        theirs.sendall(b"HTTP/1.1 200 OK\nContent-Type: gnss/data\n\r\n")

        start = time.monotonic()
        read_reply(ours, timeout=2.0)

        assert time.monotonic() - start < 0.5

    def test_a_v1_status_line_is_returned_without_waiting_for_more(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link
        theirs.sendall(b"ICY 200 OK\r\n")

        start = time.monotonic()
        reply = read_reply(ours, timeout=2.0)

        assert reply.outcome is NtripOutcome.ACCEPTED
        assert time.monotonic() - start < 0.5

    def test_no_status_line_in_time_is_a_caster_error(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, _ = caster_link

        with pytest.raises(NtripConnectionError, match="timeout") as raised:
            read_reply(ours, timeout=0.2)
        assert raised.value.reason is NtripFailure.CASTER

    def test_a_caster_that_closes_without_replying_is_a_bad_reply(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link
        theirs.close()

        assert read_reply(ours, timeout=1.0).outcome is NtripOutcome.BAD_REPLY

    def test_an_endless_header_block_is_cut_off_as_a_bad_reply(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link

        def _flood() -> None:
            theirs.sendall(b"HTTP/1.1 200 OK\r\n")
            try:
                for _ in range(10_000):
                    theirs.sendall(b"X-Filler: " + b"a" * 100 + b"\r\n")
            except OSError:
                pass

        threading.Thread(target=_flood, daemon=True).start()

        assert read_reply(ours, timeout=2.0).outcome is NtripOutcome.BAD_REPLY

    def test_the_socket_timeout_is_restored(
        self, caster_link: tuple[socket.socket, socket.socket]
    ) -> None:
        ours, theirs = caster_link
        ours.settimeout(30.0)
        theirs.sendall(b"ICY 200 OK\r\n")

        read_reply(ours, timeout=2.0)

        assert ours.gettimeout() == 30.0


class TestRequests:
    def test_v1_source_request(self) -> None:  # the destination's v1 bytes, unchanged
        assert source_request("MY_MOUNT", "my_password") == (
            f"SOURCE my_password /MY_MOUNT\r\nSource-Agent: {UA}\r\n\r\n".encode()
        )

    def test_v2_post_request(self) -> None:  # the destination's v2 bytes, unchanged
        assert (
            post_request(
                "servers.onocoy.com", "ONOCOY_MOUNT", "onocoy_user", "onocoy_pass"
            )
            == (
                "POST /ONOCOY_MOUNT HTTP/1.1\r\n"
                "Host: servers.onocoy.com\r\n"
                "Ntrip-Version: Ntrip/2.0\r\n"
                "Authorization: Basic b25vY295X3VzZXI6b25vY295X3Bhc3M=\r\n"
                f"User-Agent: {UA}\r\n"
                "Transfer-Encoding: chunked\r\n"
                "\r\n"
            ).encode()
        )

    def test_v1_get_request_still_sends_host(self) -> None:
        assert (
            get_request("caster.example", "MP1", "1.0", "rover", "roverpw")
            == (
                "GET /MP1 HTTP/1.0\r\n"
                "Host: caster.example\r\n"
                f"User-Agent: {UA}\r\n"
                "Authorization: Basic cm92ZXI6cm92ZXJwdw==\r\n"
                "\r\n"
            ).encode()
        )

    def test_v2_get_request(self) -> None:
        assert (
            get_request("caster.example", "MP1", "2.0", "rover", "roverpw")
            == (
                "GET /MP1 HTTP/1.1\r\n"
                "Host: caster.example\r\n"
                "Ntrip-Version: Ntrip/2.0\r\n"
                f"User-Agent: {UA}\r\n"
                "Authorization: Basic cm92ZXI6cm92ZXJwdw==\r\n"
                "\r\n"
            ).encode()
        )

    def test_get_without_a_username_sends_no_authorization(self) -> None:
        request = get_request("caster.example", "MP1", "2.0")

        assert b"Authorization" not in request

    def test_get_appends_extra_headers(self) -> None:
        request = get_request(
            "caster.example", "MP1", "2.0", extra_headers=[("Ntrip-GGA", "$GPGGA,...")]
        )

        assert request.endswith(b"Ntrip-GGA: $GPGGA,...\r\n\r\n")


@pytest.fixture
def listener() -> Iterator[Callable[[Callable[[socket.socket], None]], int]]:
    """Start a localhost TCP listener that hands each accepted connection to a handler."""
    servers: list[socket.socket] = []

    def _start(handle: Callable[[socket.socket], None]) -> int:
        server = socket.create_server(("127.0.0.1", 0))
        servers.append(server)

        def _serve() -> None:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                try:
                    handle(conn)
                except OSError:
                    pass

        threading.Thread(target=_serve, daemon=True).start()
        port: int = server.getsockname()[1]
        return port

    yield _start
    for server in servers:
        server.close()


@pytest.fixture(scope="module")
def self_signed_cert(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A throwaway self-signed certificate for localhost (not in any CA store)."""
    if shutil.which("openssl") is None:
        pytest.skip("openssl not installed")
    folder = tmp_path_factory.mktemp("tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )
    return cert, key


def _hold_open(conn: socket.socket) -> None:
    """Read and ignore everything until the client goes away."""
    while conn.recv(4096):
        pass


class TestOpenConnection:
    def test_connects_with_tcp_keepalive(
        self, listener: Callable[[Callable[[socket.socket], None]], int]
    ) -> None:
        port = listener(_hold_open)

        sock = open_connection("127.0.0.1", port, timeout=2.0)

        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        sock.close()

    def test_a_closed_port_is_refused(self) -> None:
        unused = socket.create_server(("127.0.0.1", 0))
        port = unused.getsockname()[1]
        unused.close()

        with pytest.raises(NtripConnectionError, match="connection failed") as raised:
            open_connection("127.0.0.1", port, timeout=2.0)
        assert raised.value.reason is NtripFailure.CONNECT
        assert raised.value.connect_failure is ConnectFailure.REFUSED

    def test_an_unknown_host_is_a_dns_failure(self) -> None:
        with pytest.raises(NtripConnectionError) as raised:
            open_connection("caster.invalid", 2101, timeout=5.0)
        assert raised.value.connect_failure is ConnectFailure.DNS

    def test_no_answer_in_time_is_a_timeout(
        self, listener: Callable[[Callable[[socket.socket], None]], int]
    ) -> None:
        port = listener(_hold_open)  # accepts TCP, never answers the TLS hello

        with pytest.raises(NtripConnectionError) as raised:
            open_connection("127.0.0.1", port, timeout=0.3, tls=True)
        assert raised.value.connect_failure is ConnectFailure.TIMEOUT

    def test_a_caster_that_does_not_speak_tls_fails_the_handshake(
        self, listener: Callable[[Callable[[socket.socket], None]], int]
    ) -> None:
        def _plain_ntrip(conn: socket.socket) -> None:
            conn.recv(4096)
            conn.sendall(b"ICY 200 OK\r\n\r\n")

        port = listener(_plain_ntrip)

        with pytest.raises(NtripConnectionError) as raised:
            open_connection("127.0.0.1", port, timeout=2.0, tls=True)
        assert raised.value.connect_failure is ConnectFailure.TLS_HANDSHAKE

    def test_an_untrusted_certificate_is_rejected(
        self,
        listener: Callable[[Callable[[socket.socket], None]], int],
        self_signed_cert: tuple[Path, Path],
    ) -> None:
        server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_tls.load_cert_chain(*self_signed_cert)

        def _tls_caster(conn: socket.socket) -> None:
            with server_tls.wrap_socket(conn, server_side=True) as tls_conn:
                tls_conn.recv(4096)

        port = listener(_tls_caster)

        with pytest.raises(NtripConnectionError) as raised:
            open_connection("localhost", port, timeout=2.0, tls=True)
        assert raised.value.connect_failure is ConnectFailure.TLS_CERTIFICATE
