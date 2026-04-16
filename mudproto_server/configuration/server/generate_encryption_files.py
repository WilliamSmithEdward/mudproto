from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError as exc:  # pragma: no cover - runtime guidance path
    raise SystemExit(
        "Missing dependency 'cryptography'. Install requirements first, then rerun this script."
    ) from exc


SERVER_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = SERVER_DIR / "settings.json"
ENCRYPTION_DIR = SERVER_DIR / "encryption"
CERT_FILE = ENCRYPTION_DIR / "server-cert.pem"
KEY_FILE = ENCRYPTION_DIR / "server-key.pem"
CA_FILE = ENCRYPTION_DIR / "server-ca.pem"
INFO_FILE = ENCRYPTION_DIR / "tls-info.json"


def _load_settings() -> dict:
    with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Server settings must be a JSON object.")
    return raw


def _save_settings(settings: dict) -> None:
    with SETTINGS_FILE.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")


def _ensure_network_tls_paths(settings: dict) -> None:
    network = settings.setdefault("network", {})
    if not isinstance(network, dict):
        raise ValueError("The 'network' settings section must be a JSON object.")

    network.setdefault("host", "localhost")
    network.setdefault("port", 8765)
    network.setdefault("tls_enabled", False)
    network["tls_certfile"] = "configuration/server/encryption/server-cert.pem"
    network["tls_keyfile"] = "configuration/server/encryption/server-key.pem"
    network["tls_ca_file"] = "configuration/server/encryption/server-ca.pem"
    network.setdefault("tls_verify_server", False)


def _generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=4096)


def _generate_self_signed_certificate(private_key: rsa.RSAPrivateKey) -> x509.Certificate:
    now = datetime.now(timezone.utc)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MudProto Local Development"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])

    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.IPAddress(ipaddress.ip_address("::1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )


def _write_files(private_key: rsa.RSAPrivateKey, certificate: x509.Certificate) -> None:
    ENCRYPTION_DIR.mkdir(parents=True, exist_ok=True)

    KEY_FILE.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    CERT_FILE.write_bytes(cert_bytes)
    CA_FILE.write_bytes(cert_bytes)

    info = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "certfile": str(CERT_FILE),
        "keyfile": str(KEY_FILE),
        "ca_file": str(CA_FILE),
        "dns_names": ["localhost"],
        "ip_addresses": ["127.0.0.1", "::1"],
        "expires_at": certificate.not_valid_after_utc.isoformat(),
        "tls_enabled": False,
        "tls_verify_server": False,
        "note": "Set tls_enabled to true in settings.json when you are ready to use the generated files.",
    }
    INFO_FILE.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    settings = _load_settings()
    _ensure_network_tls_paths(settings)

    private_key = _generate_private_key()
    certificate = _generate_self_signed_certificate(private_key)
    _write_files(private_key, certificate)
    _save_settings(settings)

    print("Generated local TLS materials:")
    print(f"- Certificate: {CERT_FILE}")
    print(f"- Private key: {KEY_FILE}")
    print(f"- CA bundle:   {CA_FILE}")
    print(f"- Metadata:    {INFO_FILE}")
    print()
    print("Next steps:")
    print("1. Set 'tls_enabled' to true in settings.json.")
    print("2. Restart the server and GUI client.")
    print("3. For stricter client verification, set 'tls_verify_server' to true.")


if __name__ == "__main__":
    main()
