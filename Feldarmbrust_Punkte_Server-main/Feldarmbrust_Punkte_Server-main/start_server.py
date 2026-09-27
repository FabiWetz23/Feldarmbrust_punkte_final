#!/usr/bin/env python3
"""Start script for the Feldarmbrust scoring server."""

import ipaddress
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CONFIG_FILE = "server_config.json"
CERT_DIR = "certs"
PORT = 8000


def app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_config(base_dir: str) -> dict:
    path = Path(base_dir) / CONFIG_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(base_dir: str, config: dict) -> None:
    path = Path(base_dir) / CONFIG_FILE
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def local_ipv4_addresses() -> list[str]:
    addresses = set()
    hostname = socket.gethostname()

    try:
        for value in socket.gethostbyname_ex(hostname)[2]:
            ip = ipaddress.ip_address(value)
            if ip.version == 4 and not ip.is_loopback:
                addresses.add(str(ip))
    except Exception:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            value = sock.getsockname()[0]
            ip = ipaddress.ip_address(value)
            if ip.version == 4 and not ip.is_loopback:
                addresses.add(str(ip))
    except Exception:
        pass

    return sorted(addresses)


def cert_name(value: str):
    try:
        return x509.IPAddress(ipaddress.ip_address(value))
    except ValueError:
        return x509.DNSName(value)


def generate_ca(certs_dir: Path) -> tuple[object, x509.Certificate]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Feldarmbrust Local CA")])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
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
    (certs_dir / "ca.crt").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (certs_dir / "ca.cer").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    (certs_dir / "ca.key").write_bytes(
        ca_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return ca_key, ca_cert


def load_or_create_ca(certs_dir: Path) -> tuple[object, x509.Certificate]:
    ca_cert_path = certs_dir / "ca.crt"
    ca_key_path = certs_dir / "ca.key"
    if ca_cert_path.exists() and ca_key_path.exists():
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        if not (certs_dir / "ca.cer").exists():
            (certs_dir / "ca.cer").write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        return ca_key, ca_cert
    return generate_ca(certs_dir)


def server_cert_matches(cert_path: Path, names: list[str]) -> bool:
    if not cert_path.exists():
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        if cert.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=14):
            return False
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        existing = set()
        existing.update(str(ip) for ip in san.get_values_for_type(x509.IPAddress))
        existing.update(san.get_values_for_type(x509.DNSName))
        return all(name in existing for name in names)
    except Exception:
        return False


def write_server_certificate(certs_dir: Path, ca_key, ca_cert: x509.Certificate, host_names: list[str]) -> None:
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    primary_name = host_names[0]
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, primary_name)])
    now = datetime.now(timezone.utc)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([cert_name(name) for name in host_names]), critical=False)
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
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (certs_dir / "server.crt").write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    (certs_dir / "server.key").write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def ensure_tls_certificates(base_dir: str) -> tuple[str, str, list[str]]:
    certs_dir = Path(base_dir) / CERT_DIR
    certs_dir.mkdir(parents=True, exist_ok=True)
    ips = local_ipv4_addresses()
    host_names = ["localhost", "127.0.0.1", socket.gethostname(), *ips]

    ca_key, ca_cert = load_or_create_ca(certs_dir)
    certfile = certs_dir / "server.crt"
    keyfile = certs_dir / "server.key"
    if not keyfile.exists() or not server_cert_matches(certfile, host_names):
        write_server_certificate(certs_dir, ca_key, ca_cert, host_names)

    return str(certfile), str(keyfile), ips


def write_setup_readme(base_dir: str, server_urls: list[str]) -> None:
    lines = [
        "Feldarmbrust Server Setup",
        "=========================",
        "",
        "1. Server starten:",
        "   Feldarmbrust_Server.exe ausfuehren.",
        "",
        "2. Tablet-Zertifikat installieren:",
        "   Oeffne am Tablet eine dieser Adressen und lade ca.cer herunter:",
        *[f"   {url}/ca.cer" for url in server_urls],
        "",
        "   Danach ca.cer in Android installieren:",
        "   Einstellungen > Sicherheit > Verschluesselung & Anmeldedaten > Zertifikat installieren > CA-Zertifikat.",
        "",
        "3. Tablet-App verbinden:",
        "   In der App als Server-URL eine dieser Adressen eintragen:",
        *[f"   {url}" for url in server_urls],
        "",
    ]
    (Path(base_dir) / "TABLET_SETUP.txt").write_text("\n".join(lines), encoding="utf-8")


def open_browser_later(url: str) -> None:
    def _open() -> None:
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    base_dir = app_base_dir()
    os.chdir(base_dir)

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not getattr(sys, "frozen", False) and not os.path.exists("app"):
        print("Error: app/ folder not found.")
        print("Start the EXE from the server folder.")
        sys.exit(1)

    config = load_config(base_dir)
    if os.environ.get("FELDARMBRUST_API_KEY"):
        password = os.environ["FELDARMBRUST_API_KEY"]
    else:
        password = config.get("api_key")
        if not password:
            password = input("Choose server password / API key (Enter = 1234): ").strip() or "1234"
            config["api_key"] = password
            save_config(base_dir, config)
        os.environ["FELDARMBRUST_API_KEY"] = password

    certfile, keyfile, ips = ensure_tls_certificates(base_dir)
    os.environ["FELDARMBRUST_TLS_CERTFILE"] = certfile
    os.environ["FELDARMBRUST_TLS_KEYFILE"] = keyfile

    scheme = "https"
    local_url = f"{scheme}://localhost:{PORT}"
    tablet_urls = [f"{scheme}://{ip}:{PORT}" for ip in ips]
    server_urls = tablet_urls or [local_url]
    setup_url = f"{server_urls[0]}/setup"
    write_setup_readme(base_dir, server_urls)

    print("Feldarmbrust scoring server")
    print("=" * 50)
    print("Server setup complete.")
    print(f"Local page: {local_url}")
    print(f"Tablet setup page: {setup_url}")
    print("Tablet server URL:")
    for server_url in server_urls:
        print(f"  {server_url}")
    print("Tablet certificate download:")
    for server_url in server_urls:
        print(f"  {server_url}/ca.cer")
    print(f"Setup notes: {os.path.join(base_dir, 'TABLET_SETUP.txt')}")
    print(f"Password/API key: {password}")
    print("TLS: enabled")
    print("=" * 50)
    print("Press CTRL+C to stop")
    print()

    open_browser_later(setup_url)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
        ssl_certfile=certfile,
        ssl_keyfile=keyfile,
    )


if __name__ == "__main__":
    main()
