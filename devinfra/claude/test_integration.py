"""Integration tests for claude proxy infrastructure.

These tests use a mitmproxy container to verify CA extraction behavior.
"""

from pathlib import Path

import pytest
import pytest_bazel
from cryptography import x509
from cryptography.x509.oid import NameOID

from devinfra.claude.auth_proxy import setup as proxy_setup
from devinfra.claude.session_paths import SessionPaths
from devinfra.claude.settings import HookSettings
from devinfra.claude.testing.mitmproxy_fixture import MitmproxyFixture

# Register shared fixtures (isolated_dirs, session_paths, hook_settings, mitmproxy_proxy)
pytest_plugins = ["devinfra.claude.testing.fixtures", "devinfra.claude.testing.mitmproxy_fixture"]


@pytest.fixture
def hook_settings(
    isolated_dirs, mitmproxy_proxy: MitmproxyFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> HookSettings:
    """Override shared hook_settings to also configure upstream proxy and CA path."""
    # Set HTTPS_PROXY (uppercase) which get_upstream_proxy_url() checks first.
    # Also clear lowercase to avoid ambiguity.
    monkeypatch.setenv("HTTPS_PROXY", mitmproxy_proxy.url)
    monkeypatch.delenv("https_proxy", raising=False)
    # Write mock CA to a temp file so _extract_proxy_ca can load it from filesystem
    ca_file = tmp_path / "mock-ca.crt"
    ca_file.write_bytes(mitmproxy_proxy.ca_cert_pem)
    monkeypatch.setenv("ANTHROPIC_CA_PATH", str(ca_file))
    return HookSettings()


async def test_ca_extraction(session_paths: SessionPaths, hook_settings: HookSettings) -> None:
    """Test that CA certificate is extracted from the filesystem."""
    proxy_setup._extract_proxy_ca(session_paths)

    ca_file = session_paths.auth_proxy_ca_file
    assert ca_file.exists(), "CA file should be created"

    ca_content = ca_file.read_text()
    assert "BEGIN CERTIFICATE" in ca_content

    cert = x509.load_pem_x509_certificate(ca_content.encode())
    cn_value = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    cn = cn_value if isinstance(cn_value, str) else cn_value.decode()
    assert "TLS Inspection CA" in cn, f"Expected 'TLS Inspection CA' in CN, got: {cn}"


if __name__ == "__main__":
    pytest_bazel.main()
