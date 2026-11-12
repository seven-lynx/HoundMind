"""TLS for the control plane: off by default, generated on demand, refused by name when it cannot be.

The certificate is produced by the `openssl` binary, so the one test that needs a real pair skips when
that binary is not on PATH rather than pretending the path was exercised. What has to hold on every
machine is the decision of *whether* to generate, and what the operator is told when the answer is no.
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path

import pytest

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services import tls
from houndmind_ai.services.api import ControlPlane
from houndmind_ai.services.module import ControlPlaneModule
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.tls import TlsError, build_context

HAVE_OPENSSL = tls.shutil.which("openssl") is not None


class DummyContext:
    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def enabled(tmp_path: Path, **overrides) -> ApiSettings:
    """TLS switched on, with both files under `tmp_path` so nothing touches `~/.houndmind`."""
    paths = {
        "tls_enabled": True,
        "tls_cert": str(tmp_path / "tls" / "cert.pem"),
        "tls_key": str(tmp_path / "tls" / "key.pem"),
    }
    paths.update(overrides)
    return ApiSettings(**paths)


def test_tls_is_off_unless_it_is_asked_for(tmp_path) -> None:
    """The shipped posture: plaintext, and `None` is what `TCPSite` serves that with."""
    assert ApiSettings().tls_enabled is False
    assert ApiSettings.from_settings({}).tls_enabled is False
    assert build_context(ApiSettings(tls_cert=str(tmp_path / "c"), tls_key=str(tmp_path / "k"))) is None
    assert not (tmp_path / "c").exists(), "a disabled feature must not generate a certificate"


def test_the_settings_coerce_the_tls_fields() -> None:
    settings = ApiSettings.from_settings(
        {"api": {"tls_enabled": True, "tls_cert": "/tmp/c.pem", "tls_key": "/tmp/k.pem"}}
    )
    assert settings.tls_enabled is True
    assert settings.tls_cert == "/tmp/c.pem"
    assert settings.tls_key == "/tmp/k.pem"

    # Not `bool("yes")`: a string is never a switch that guards a transport change.
    assert ApiSettings.from_settings({"api": {"tls_enabled": "yes"}}).tls_enabled is False
    assert ApiSettings.from_settings({"api": {"tls_cert": ""}}).tls_cert.endswith("cert.pem")


def test_a_missing_openssl_is_named_not_raised(tmp_path, monkeypatch) -> None:
    """The Pi's image is not something this stack controls, so absence is a message, not a trace."""

    monkeypatch.setattr(tls.shutil, "which", lambda _name: None)
    with pytest.raises(TlsError) as caught:
        build_context(enabled(tmp_path))
    assert "openssl" in str(caught.value)


def test_an_unreadable_pair_is_refused_by_name(tmp_path) -> None:
    settings = enabled(tmp_path)
    Path(settings.tls_cert).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.tls_cert).write_text("not a certificate", encoding="utf-8")
    Path(settings.tls_key).write_text("not a key", encoding="utf-8")
    with pytest.raises(TlsError) as caught:
        build_context(settings)
    assert "could not load the certificate" in str(caught.value)


@pytest.mark.skipif(not HAVE_OPENSSL, reason="openssl is not on PATH")
def test_a_generated_pair_loads_into_a_server_context(tmp_path) -> None:
    settings = enabled(tmp_path)
    context = build_context(settings)

    assert isinstance(context, ssl.SSLContext)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert Path(settings.tls_cert).exists()
    assert Path(settings.tls_key).exists()
    if os.name != "nt":
        # The key is the secret; the certificate is meant to be copied to a phone.
        assert (Path(settings.tls_key).stat().st_mode & 0o777) == 0o600
        assert (Path(settings.tls_cert).stat().st_mode & 0o777) == 0o644

    # A second start reuses the pair instead of issuing a new certificate under a trusted name.
    before = Path(settings.tls_cert).read_text(encoding="utf-8")
    build_context(settings)
    assert Path(settings.tls_cert).read_text(encoding="utf-8") == before


def test_meta_reports_the_scheme_it_is_served_on(tmp_path) -> None:
    plain = ControlPlane(DummyContext({}), ApiSettings(), CommandBus())
    assert plain.meta()["scheme"] == "http"

    secure = ControlPlane(DummyContext({}), enabled(tmp_path), CommandBus())
    assert secure.meta()["scheme"] == "https"


def test_a_tls_failure_disables_the_module_instead_of_the_runtime(tmp_path, monkeypatch) -> None:
    """A bad certificate is a configuration problem: the dog must keep walking without the API."""

    def boom(_settings):
        raise TlsError("openssl is not installed, so no self-signed certificate could be generated")

    monkeypatch.setattr("houndmind_ai.services.module.build_context", boom)
    context = DummyContext(
        {
            "api": {
                "tls_enabled": True,
                "tls_cert": str(tmp_path / "tls" / "cert.pem"),
                "tls_key": str(tmp_path / "tls" / "key.pem"),
            }
        }
    )
    module = ControlPlaneModule("api", bus=CommandBus())
    module.start(context)

    assert module.status.enabled is False
    assert "openssl" in (module.status.disabled_reason or "")
    module.stop(context)
