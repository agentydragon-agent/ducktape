"""Proxy CA generation and upstream proxy config for testing.

Provides mock CA certificates matching Anthropic's real format and upstream
proxy detection for chaining through the egress proxy in test environments.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from devinfra.claude.auth_proxy.setup import SSL_CA_ENV_VARS
from devinfra.claude.auth_proxy.vars import get_upstream_proxy_url

logger = logging.getLogger(__name__)


@dataclass
class EgressProxyConfig:
    """Configuration for upstream proxy."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    ca_bundle: Path | None = None

    @classmethod
    def from_env(cls) -> EgressProxyConfig | None:
        """Parse upstream proxy from environment variables.

        Looks for HTTPS_PROXY or https_proxy in format:
        http://user:pass@host:port or http://host:port

        Localhost proxies (e.g. the auth proxy at localhost:18081)
        are valid upstream targets — they forward to the real egress proxy.
        """
        proxy_url = get_upstream_proxy_url()
        if not proxy_url:
            return None

        parsed = urllib.parse.urlparse(proxy_url)
        if not parsed.hostname:
            return None

        # Get CA bundle for verifying upstream proxy's TLS interception cert.
        ca_bundle_str = next((v for var in SSL_CA_ENV_VARS if (v := os.environ.get(var))), None)
        ca_bundle = Path(ca_bundle_str) if ca_bundle_str else None

        return cls(
            host=parsed.hostname,
            port=parsed.port or 8080,
            username=urllib.parse.unquote(parsed.username) if parsed.username else None,
            password=urllib.parse.unquote(parsed.password) if parsed.password else None,
            ca_bundle=ca_bundle,
        )


def generate_mock_ca() -> tuple[bytes, bytes]:
    """Generate a self-signed CA cert matching Anthropic's real CA format.

    Returns (cert_pem, key_pem) tuple.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Anthropic"),
            x509.NameAttribute(NameOID.COMMON_NAME, "sandbox-egress-production TLS Inspection CA"),
        ]
    )

    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    aki = x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key())

    key_usage = x509.KeyUsage(
        key_cert_sign=True,
        crl_sign=True,
        digital_signature=False,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        encipher_only=False,
        decipher_only=False,
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(key_usage, critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(ski, critical=False)
        .add_extension(aki, critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    )
    return cert_pem, key_pem
