"""TLS for the control plane: opt-in, self-signed on first start (`#18`).

Off is the default, and `build_context` returning `None` is exactly what `TCPSite` needs to hear for
that — aiohttp serves plain HTTP when `ssl_context` is `None`, so the caller does not have to branch
on the feature twice.

A certificate is generated **only when TLS is already switched on**. Generating one at install time
would put a key on every device that never enables the feature, and a file that looks like a decision
nobody made is worse than an absent one.

It is generated with `openssl` rather than the `cryptography` package. This repo depends on neither,
a Pi 3 armhf wheel is a larger risk than a binary Raspberry Pi OS already ships, and when the binary
is absent the control plane disables with a message naming it instead of raising into the runtime.
That the image ships `openssl` is a hypothesis until `openssl version` is run on the device.
"""

from __future__ import annotations

import logging
import shutil
import socket
import ssl
import subprocess
from pathlib import Path

from houndmind_ai.services.settings import ApiSettings

logger = logging.getLogger(__name__)

__all__ = ["TlsError", "build_context"]

# Ten years. A self-signed certificate that expires in 90 days becomes a support ticket on a dog
# nobody has looked at for a season; the key, not the expiry, is the thing that has to stay private.
_CERT_DAYS = 3650


class TlsError(Exception):
    """TLS was asked for and could not be set up. The message is meant for the user."""


def _local_addresses() -> list[str]:
    """Every address this host answers on, best effort, for the certificate's SAN list."""
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(str(info[4][0]))
    except OSError:
        # A Pi with no DHCP lease resolves nothing; the hostname SAN is still worth generating.
        logger.debug("Could not resolve the hostname for the certificate SAN", exc_info=True)
    return sorted(addresses)


def _subject_alt_names(hostname: str) -> str:
    entries = [f"DNS:{hostname}", "DNS:localhost", "IP:127.0.0.1"]
    entries.extend(f"IP:{address}" for address in _local_addresses())
    return ",".join(entries)


def _generate(cert_path: Path, key_path: Path) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise TlsError(
            "openssl is not installed, so no self-signed certificate could be generated; install it "
            "or point settings.api.tls_cert and settings.api.tls_key at an existing pair"
        )
    hostname = socket.gethostname() or "houndmind"
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cert_path.parent.chmod(0o700)
    except OSError:
        logger.debug("Could not restrict %s to 0700", cert_path.parent)
    command = [
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        # No passphrase: the server has to start unattended, and the key is protected by its mode.
        "-nodes",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-days",
        str(_CERT_DAYS),
        "-subj",
        f"/CN={hostname}",
        "-addext",
        f"subjectAltName={_subject_alt_names(hostname)}",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        stderr = getattr(exc, "stderr", b"") or b""
        detail = stderr.decode("utf-8", "replace").strip() or str(exc)
        raise TlsError(f"could not generate a certificate: {detail}") from exc
    for path, mode in ((cert_path, 0o644), (key_path, 0o600)):
        try:
            path.chmod(mode)
        except OSError:
            logger.debug("Could not set the mode on %s", path)
    logger.warning(
        "Generated a self-signed certificate at %s; each client must trust it before the control "
        "plane is reachable over https",
        cert_path,
    )


def build_context(settings: ApiSettings) -> ssl.SSLContext | None:
    """An `SSLContext` for these settings, or `None` when TLS is switched off.

    Raises `TlsError` rather than `OSError`/`ssl.SSLError`: every one of these failures is a
    configuration problem the operator can fix, and the message says which one.
    """
    if not settings.tls_enabled:
        return None
    cert_path = Path(settings.tls_cert).expanduser()
    key_path = Path(settings.tls_key).expanduser()
    if not cert_path.exists() or not key_path.exists():
        _generate(cert_path, key_path)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    # 1.2 is the floor: everything on a home LAN speaks it, and 1.0/1.1 are deprecated.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    except (OSError, ssl.SSLError) as exc:
        raise TlsError(f"could not load the certificate at {cert_path}: {exc}") from exc
    return context
