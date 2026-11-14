"""Advertise the control plane on the LAN, so a client is not handed an address by hand.

Nothing in the runtime told a client *where* the dog is. `GET /meta` describes the device and names
no host, no port and no URL, and the port the control plane binds never left the process - so every
client had to be told an IP address, and DHCP changes those on the next lease (#38).

This module publishes one mDNS service (`_houndmind._tcp.local`) carrying the host, the port and the
API version, and withdraws it on a clean stop. Three rules it keeps:

- **The record is public.** Whatever it advertises is already in the unauthenticated `/meta`
  payload: no token, no device secret, no location. `services/module.py` builds the TXT entries from
  `meta()`, and `tests/test_discovery.py` asserts they are a subset of it.
- **Discovery is a convenience, never a boot dependency.** A blocked multicast group, a container
  without a route or a port already taken costs one log line and nothing else.
- **The standard library only.** `zeroconf` would be a dependency on every install, `lite`
  included, to save a few dozen lines of DNS wire format.

RFC 6762 in the small: announce a few times, answer a query that names us, send the same records
with a zero TTL on the way out.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading

logger = logging.getLogger(__name__)

__all__ = ["GROUP", "MDNS_PORT", "SERVICE_TYPE", "MdnsAdvertiser", "parse_question"]

# The link-local multicast group and port every mDNS responder listens on. Fixed by the RFC.
GROUP = "224.0.0.251"
MDNS_PORT = 5353

# `_service._proto.local`, the name a resolver asks about. The instance is prefixed onto it, so one
# dog is `houndmind._houndmind._tcp.local`.
SERVICE_TYPE = "_houndmind._tcp.local"

_TTL = 120
_GOODBYE_TTL = 0
_ANNOUNCE_COUNT = 3
_ANNOUNCE_INTERVAL_S = 1.0
_POLL_TIMEOUT_S = 1.0

_TYPE_A = 1
_TYPE_PTR = 12
_TYPE_TXT = 16
_TYPE_SRV = 33
_CLASS_IN = 1
# RFC 6762: a record we own is marked cache-flush so a resolver drops its older copy.

# ------------------------------------------------------------------ wire format


def _encode_name(name: str) -> bytes:
    """A DNS name as length-prefixed labels. Uncompressed: bigger, and simpler to get right."""
    out = b""
    for label in name.strip(".").split("."):
        if not label:
            continue
        raw = label.encode("utf-8")
        if len(raw) > 63:
            raise ValueError(f"mDNS label too long: {label!r}")
        out += bytes([len(raw)]) + raw
    return out + b"\x00"


def _record(name: str, rtype: int, rdata: bytes, ttl: int, cache_flush: bool = False) -> bytes:
    rclass = _CLASS_IN_FLUSH if cache_flush else _CLASS_IN
    return _encode_name(name) + struct.pack("!HHIH", rtype, rclass, ttl, len(rdata)) + rdata


def _srv_rdata(host: str, port: int) -> bytes:
    # Priority and weight are 0: there is one service, so there is nothing to rank.
    return struct.pack("!HHH", 0, 0, port) + _encode_name(host)


def _txt_rdata(entries: dict[str, str]) -> bytes:
    out = b""
    for key, value in entries.items():
        item = f"{key}={value}".encode()
        if len(item) > 255:  # one TXT string is capped at 255 bytes: skip rather than truncate
            logger.debug("Skipping over-long mDNS TXT entry %r", key)
            continue
        out += bytes([len(item)]) + item
    # An empty TXT set is a single empty string, which is what every responder sends.
    return out or b"\x00"


def encode_response(records: list[bytes]) -> bytes:
    """Wrap answer records in a response header. Public so a test can build one without a socket."""
    header = struct.pack("!HHHHHH", 0, _RESPONSE_FLAGS, 0, len(records), 0, 0)
    return header + b"".join(records)


def parse_question(data: bytes) -> tuple[str, int] | None:
    """`(qname, qtype)` from the first question of a query, or ``None``.

    Only the first question is needed: this responder answers with its whole record set, so a
    client asking for the A record and one asking for PTR get the same reply.
    """
    if len(data) < 12:
        return None
    _ident, _flags, qdcount, _an, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
    if qdcount < 1:
        return None
    labels: list[str] = []
    index = 12
    while index < len(data):
        length = data[index]
        if length == 0:
            index += 1
            break
        if length & 0xC0:
            # A compression pointer inside a question. Legal, but no client sends one for the
            # question it is asking, and resolving one is work this responder never needs.
            return None
        index += 1
        if index + length > len(data):
            return None
        labels.append(data[index : index + length].decode("utf-8", "replace"))
        index += length
    if not labels or index + 4 > len(data):
        return None
    qtype = struct.unpack("!H", data[index : index + 2])[0]
    return ".".join(labels).lower(), qtype


def _local_addresses() -> list[str]:
    """The IPv4 addresses a client could reach, best effort.

    No address at all is not a failure: the SRV record still names the host, and a resolver that
    can answer for that name does its own lookup. Nothing here raises.
    """
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError as exc:
        logger.debug("mDNS has no address to publish: %s", exc)
        return []
    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address and not address.startswith("127.") and address not in addresses:
            addresses.append(address)
    return addresses


def _default_host() -> str:
    """`<hostname>.local`, the name a client can resolve without being told an address."""
    name = socket.gethostname().split(".")[0].strip() or "houndmind"
    return f"{name}.local"


# ------------------------------------------------------------------ the advertiser


class MdnsAdvertiser:
    """One service record, for as long as the control plane holds its port.

    Not a `Module`: the record has to exist exactly as long as the socket it describes, and
    `services/module.py::_serve` is the only place that knows both facts. `start()` returning False
    means the record does not exist and the plane runs anyway.
    """

    def __init__(
        self,
        port: int,
        service_name: str = "houndmind",
        txt: dict[str, str] | None = None,
        host: str | None = None,
    ) -> None:
        self.port = int(port)
        self.service_name = (service_name or "houndmind").strip() or "houndmind"
        self.txt = dict(txt or {})
        self.host = (host or _default_host()).lower()
        self.instance = f"{self.service_name}.{SERVICE_TYPE}"
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._addresses: list[str] = []

    # ---- the record --------------------------------------------------------

    def records(self, ttl: int = _TTL) -> list[bytes]:
        """The answer set: PTR, SRV, TXT, and one A per address we know."""
        records = [
            _record(SERVICE_TYPE, _TYPE_PTR, _encode_name(self.instance), ttl),
            _record(
                self.instance, _TYPE_SRV, _srv_rdata(self.host, self.port), ttl, cache_flush=True
            ),
            _record(self.instance, _TYPE_TXT, _txt_rdata(self.txt), ttl, cache_flush=True),
        ]
        for address in self._addresses:
            records.append(
                _record(self.host, _TYPE_A, socket.inet_aton(address), ttl, cache_flush=True)
            )
        return records

    def payload(self) -> bytes:
        """The announcement as it goes on the wire. Public so a test can read it without a socket."""
        return encode_response(self.records())

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Join the group and announce. False means advertising is off; nothing else changes."""
        if self.port <= 0:
            # An ephemeral port is a test's or a developer's; advertising it would advertise a lie.
            logger.debug("Not advertising %s: no fixed port to publish", self.instance)
            return False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", MDNS_PORT))
            # Join on the default interface: `INADDR_ANY` lets the kernel pick, which is what a
            # device with one LAN connection wants and the only thing that works portably.
            membership = socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            sock.settimeout(_POLL_TIMEOUT_S)
        except OSError as exc:
            logger.warning("mDNS advertisement unavailable: %s", exc)
            return False

        self._addresses = _local_addresses()
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="houndmind-mdns", daemon=True)
        self._thread.start()
        logger.info("Advertising %s at %s:%s", self.instance, self.host, self.port)
        return True

    def stop(self) -> None:
        """Withdraw the record, so a stale one does not outlive the process."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(_POLL_TIMEOUT_S * 2)
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.sendto(encode_response(self.records(_GOODBYE_TTL)), (GROUP, MDNS_PORT))
        except OSError as exc:
            logger.debug("mDNS goodbye was not sent: %s", exc)
        finally:
            sock.close()

    # ---- the responder -----------------------------------------------------

    def _serve(self) -> None:
        sock = self._sock
        if sock is None:
            return
        for _ in range(_ANNOUNCE_COUNT):
            self._send(self.payload())
            if self._stop.wait(_ANNOUNCE_INTERVAL_S):
                return
        while not self._stop.is_set():
            try:
                data, _peer = sock.recvfrom(9000)
            except TimeoutError:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    logger.warning("mDNS responder stopped: %s", exc)
                return
            if self._names_us(data):
                self._send(self.payload())

    def _names_us(self, data: bytes) -> bool:
        parsed = parse_question(data)
        if parsed is None:
            return False
        name, _qtype = parsed
        # A client asks for the service type, the instance, or the host; all three are ours.
        return name in {SERVICE_TYPE, self.instance.lower(), self.host}

    def _send(self, payload: bytes) -> None:
        sock = self._sock
        if sock is None:
            return
        try:
            sock.sendto(payload, (GROUP, MDNS_PORT))
        except OSError as exc:
            logger.debug("mDNS send failed: %s", exc)

_CLASS_IN_FLUSH = 0x8001

# QR | AA: this is an authoritative answer, not a query.
_RESPONSE_FLAGS = 0x8400
