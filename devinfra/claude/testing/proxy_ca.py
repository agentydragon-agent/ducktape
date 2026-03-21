"""Mock CA generation for proxy testing.

Generates self-signed CA certificates matching Anthropic's real TLS inspection
CA format, used by mitmproxy testcontainers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


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
