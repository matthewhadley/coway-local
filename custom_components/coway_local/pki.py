"""Persistent local CA and device identities. All functions run in an executor."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .const import CIPHERS


def private_write(path: Path, data: bytes | str) -> None:
    """Atomically replace a private file, without changing process-wide umask."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data.encode() if isinstance(data, str) else data)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def save_state(root: Path, data: dict) -> None:
    private_write(root / "devices.json", json.dumps(data, separators=(",", ":")))


def load_state(root: Path) -> dict:
    file = root / "devices.json"
    return json.loads(file.read_text()) if file.exists() else {"version": 1, "devices": {}}


def fingerprint(pem: bytes) -> str:
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem.decode())).hexdigest()


def _write_pair(root: Path, stem: str, key, cert) -> None:
    private_write(
        root / f"{stem}.key",
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )
    private_write(root / f"{stem}.pem", cert.public_bytes(serialization.Encoding.PEM))


def _authority(root: Path):
    key = serialization.load_pem_private_key((root / "ca.key").read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate((root / "ca.pem").read_bytes())
    return key, cert


def _issue(root: Path, stem: str, common_name: str, host: str | None = None) -> bytes:
    ca_key, ca = _authority(root)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        # The device may start without a correct clock.
        .not_valid_before(dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
        .not_valid_after(ca.not_valid_after_utc)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, False, False, False, False),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.SERVER_AUTH if host else ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False
        )
    )
    if host:
        # This firmware compares IP literals to DNS SANs. Keep both forms.
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(host)), x509.DNSName(host)]
            ),
            False,
        )
    cert = builder.sign(ca_key, hashes.SHA256())
    _write_pair(root, stem, key, cert)
    return cert.public_bytes(serialization.Encoding.PEM)


def initialize(root: Path, host: str) -> tuple[bytes, ssl.SSLContext, ssl.SSLContext]:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    if not (root / "ca.pem").exists():
        if (root / "devices.json").exists() or (root / "ca.key").exists():
            raise ValueError(
                "Incomplete certificate store; restore its backup instead of replacing it"
            )
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Coway Local CA")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
            .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(
                x509.KeyUsage(False, False, False, False, False, True, True, False, False), True
            )
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .sign(key, hashes.SHA256())
        )
        _write_pair(root, "ca", key, cert)
    server_file = root / "server.pem"
    if server_file.exists():
        cert = x509.load_pem_x509_certificate(server_file.read_bytes())
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        renew = host not in sans.get_values_for_type(
            x509.DNSName
        ) or cert.not_valid_after_utc < dt.datetime.now(dt.UTC) + dt.timedelta(days=30)
    else:
        renew = True
    if renew:
        _issue(root, "server", host, host)
    contexts = []
    for mutual in (False, True):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_ciphers(CIPHERS)
        ctx.load_cert_chain(root / "server.pem", root / "server.key")
        if mutual:
            ctx.load_verify_locations(root / "ca.pem")
            ctx.verify_mode = ssl.CERT_REQUIRED
        contexts.append(ctx)
    return (root / "ca.pem").read_bytes(), *contexts


def issue_device(root: Path, serial: str, mac: str) -> tuple[str, bytes, bytes]:
    """Serials have already passed strict validation before reaching filesystem paths."""
    stem = f"devices/{serial}"
    cert_file = root / f"{stem}.pem"
    if cert_file.exists():
        cert = cert_file.read_bytes()
    else:
        cert = _issue(root, stem, f"coway-{mac}")
    return fingerprint(cert), cert, (root / f"{stem}.key").read_bytes()
