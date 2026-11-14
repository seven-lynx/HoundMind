"""The LAN record: what it says, what it must not say, and how it fails (#38).

Every test here runs offline. The wire format is checked against the encoder itself (the same bytes
on both sides is what a resolver sees) and the socket is either absent or fake - receiving on a
multicast group is not something CI can do, and a test that needs a network fails for the wrong
reason.
"""

from __future__ import annotations

import logging
import struct

import pytest

from houndmind_ai.services import discovery
from houndmind_ai.services.discovery import (
    GROUP,
    MDNS_PORT,
    SERVICE_TYPE,
    MdnsAdvertiser,
    encode_response,
    parse_question,
)
from houndmind_ai.services.module import ControlPlaneModule
from houndmind_ai.services.settings import ApiSettings

META = {
    "api_version": 1,
    "min_client": 1,
    "scheme": "http",
    "device_id": "houndmind-dev",
    "board": "pi4",
    "board_model": "Raspberry Pi 4 Model B Rev 1.5",
    "profile": "pi4",
    "uptime_s": 12.0,
    "capabilities": ["command", "events"],
}


class FakePlane:
    """The only part of `ControlPlane` the advertiser reads."""

    def __init__(self, meta: dict) -> None:
        self._meta = meta

    def meta(self) -> dict:
        return dict(self._meta)


class FakeSocket:
    """Records what would have gone on the wire instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, payload: bytes, address) -> None:
        self.sent.append((payload, address))

    def close(self) -> None:
        self.closed = True


def _query(name: str, qtype: int = 255) -> bytes:
    """A one-question mDNS query, as a client sends it."""
    return (
        struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0)
        + discovery._encode_name(name)
        + struct.pack("!HH", qtype, 1)
    )


# ---------------------------------------------------------------- the record itself


def test_the_answer_set_names_the_service_the_instance_and_the_host() -> None:
    advertiser = MdnsAdvertiser(port=8420, txt={"api_version": "1"}, host="houndmind.local")

    payload = advertiser.payload()
    _ident, flags, questions, answers, _ns, _ar = struct.unpack("!HHHHHH", payload[:12])

    assert flags & 0x8000, "the answer bit must be set: this is a response, not a query"
    assert questions == 0
    # PTR + SRV + TXT, and no A record because this advertiser has no address to publish.
    assert answers == 3
    assert discovery._encode_name(SERVICE_TYPE) in payload
    assert discovery._encode_name("houndmind._houndmind._tcp.local") in payload
    assert discovery._encode_name("houndmind.local") in payload


def test_the_txt_record_is_a_subset_of_the_public_meta_payload(monkeypatch) -> None:
    """The record is public information, and `/meta` is what defines public here (#38)."""
    monkeypatch.setattr(MdnsAdvertiser, "start", lambda self: True)

    advertiser = ControlPlaneModule._start_advertising(ApiSettings(port=8420), FakePlane(META))

    assert advertiser is not None
    assert set(advertiser.txt) <= set(META)
    for key, value in advertiser.txt.items():
        assert value == str(META[key])


def test_discovery_can_be_switched_off(monkeypatch) -> None:
    def fail(self):
        raise AssertionError("a disabled advertiser must not open a socket")

    monkeypatch.setattr(MdnsAdvertiser, "start", fail)
    settings = ApiSettings(discovery_enabled=False)

    assert ControlPlaneModule._start_advertising(settings, FakePlane(META)) is None


def test_an_ephemeral_port_is_not_advertised() -> None:
    """A test or a developer binds port 0; advertising it would advertise somebody else's port."""
    assert MdnsAdvertiser(port=0).start() is False


# ---------------------------------------------------------------- failure and withdrawal


def test_a_blocked_multicast_group_costs_a_log_line(monkeypatch, caplog) -> None:
    def refuse(*_args, **_kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(discovery.socket, "socket", refuse)
    advertiser = MdnsAdvertiser(port=8420, txt={"api_version": "1"})

    with caplog.at_level(logging.WARNING):
        started = advertiser.start()

    assert started is False
    assert "mDNS advertisement unavailable" in caplog.text
    # A plane that could not advertise must still be stoppable without an exception.
    advertiser.stop()


def test_stopping_withdraws_the_record_with_a_zero_ttl() -> None:
    """A goodbye is the same records with TTL 0; a record outliving its socket is the bug."""
    advertiser = MdnsAdvertiser(port=8420, txt={"api_version": "1"}, host="houndmind.local")
    sock = FakeSocket()
    advertiser._sock = sock
    advertiser._addresses = ["192.168.1.50"]

    advertiser.stop()

    assert sock.closed is True
    assert len(sock.sent) == 1
    payload, address = sock.sent[0]
    assert address == (GROUP, MDNS_PORT)
    assert payload == encode_response(advertiser.records(0))
    # The goodbye is the announcement it replaces, not a different port or host.
    assert advertiser.records(0) != advertiser.records()


# ---------------------------------------------------------------- questions


def test_a_query_is_read_back_as_the_name_a_client_asked_for() -> None:
    name, qtype = parse_question(_query(SERVICE_TYPE))

    assert name == SERVICE_TYPE
    assert qtype == 255


@pytest.mark.parametrize(
    "data",
    [b"", b"\x00" * 11, struct.pack("!HHHHHH", 0, 0, 0, 0, 0, 0), b"\x00" * 12 + b"\x03ho"],
)
def test_a_packet_that_is_not_a_query_is_refused(data: bytes) -> None:
    assert parse_question(data) is None


def test_only_a_question_that_names_us_is_answered() -> None:
    advertiser = MdnsAdvertiser(port=8420, txt={"api_version": "1"}, host="houndmind.local")

    assert advertiser._names_us(_query(SERVICE_TYPE)) is True
    assert advertiser._names_us(_query("houndmind._houndmind._tcp.local")) is True
    assert advertiser._names_us(_query("houndmind.local")) is True
    assert advertiser._names_us(_query("someone-else._houndmind._tcp.local")) is False

