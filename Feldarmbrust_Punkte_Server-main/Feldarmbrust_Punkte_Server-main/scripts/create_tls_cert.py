#!/usr/bin/env python3
import ipaddress
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def san_name(value: str):
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        return x509.DNSName(value)


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/create_tls_cert.py <laptop-ip-or-hostname> [out-dir] [extra-host-or-ip ...]")
        print("Example: python scripts/create_tls_cert.py 192.168.178.110 certs 10.0.2.2")
        return 1

    host = sys.argv[1]
    out_dir = Path(sys.argv[2] if len(sys.argv) > 2 else "certs")
    extra_hosts = sys.argv[3:] if len(sys.argv) > 3 else []
    out_dir.mkdir(parents=True, exist_ok=True)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    ca_subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Feldarmbrust Local CA"),
    ])
    server_subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, host),
    ])

    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                san_name(host),
                *(san_name(name) for name in extra_hosts),
            ]),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_cert_path = out_dir / "ca.crt"
    ca_key_path = out_dir / "ca.key"
    cert_path = out_dir / "server.crt"
    key_path = out_dir / "server.key"

    ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    ca_key_path.write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    print("Created:")
    print(f"  {ca_cert_path}  <-- install this on tablet/emulator as trusted CA")
    print(f"  {ca_key_path}")
    print(f"  {cert_path}")
    print(f"  {key_path}")
    print()
    print("Start server with:")
    print("$env:FELDARMBRUST_API_KEY='dein-langes-passwort'")
    print(f"$env:FELDARMBRUST_TLS_CERTFILE='{cert_path}'")
    print(f"$env:FELDARMBRUST_TLS_KEYFILE='{key_path}'")
    print("python start_server.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
