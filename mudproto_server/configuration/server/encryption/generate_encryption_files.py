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


ENCRYPTION_DIR = Path(__file__).resolve().parent
SERVER_DIR = ENCRYPTION_DIR.parent
SETTINGS_FILE = SERVER_DIR / "settings.json"
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
    network.setdefault("tls_dns_names", ["localhost"])
    network.setdefault("tls_ip_addresses", ["127.0.0.1", "::1"])


def _normalized_unique_names(values: list[object] | tuple[object, ...]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        names.append(cleaned)
    return names


def _resolve_certificate_subject_alt_names(settings: dict) -> tuple[list[str], list[str]]:
    network = settings.get("network", {})
    if not isinstance(network, dict):
        network = {}

    dns_names: list[str] = ["localhost"]
    ip_addresses: list[str] = ["127.0.0.1", "::1"]

    raw_host = str(network.get("host", "")).strip()
    if raw_host and raw_host not in {"0.0.0.0", "::"}:
        try:
            ipaddress.ip_address(raw_host)
        except ValueError:
            dns_names.append(raw_host)
        else:
            ip_addresses.append(raw_host)

    extra_dns = network.get("tls_dns_names", [])
    if isinstance(extra_dns, list):
        dns_names.extend(extra_dns)

    extra_ips = network.get("tls_ip_addresses", [])
    if isinstance(extra_ips, list):
        ip_addresses.extend(extra_ips)

    valid_ip_addresses: list[str] = []
    for raw_ip in _normalized_unique_names(tuple(ip_addresses)):
        try:
            ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        valid_ip_addresses.append(raw_ip)

    return _normalized_unique_names(tuple(dns_names)), valid_ip_addresses


def _generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=4096)


def _generate_self_signed_certificate(private_key: rsa.RSAPrivateKey, settings: dict) -> x509.Certificate:
    now = datetime.now(timezone.utc)
    dns_names, ip_addresses = _resolve_certificate_subject_alt_names(settings)
    common_name = dns_names[0] if dns_names else (ip_addresses[0] if ip_addresses else "localhost")
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MudProto Local Development"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    subject_alt_names: list[x509.GeneralName] = [x509.DNSName(name) for name in dns_names]
    subject_alt_names.extend(x509.IPAddress(ipaddress.ip_address(raw_ip)) for raw_ip in ip_addresses)

    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(subject_alt_names),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )


def _write_files(private_key: rsa.RSAPrivateKey, certificate: x509.Certificate, settings: dict) -> None:
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

    dns_names, ip_addresses = _resolve_certificate_subject_alt_names(settings)
    network = settings.get("network", {})
    if not isinstance(network, dict):
        network = {}

    info = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "certfile": str(CERT_FILE),
        "keyfile": str(KEY_FILE),
        "ca_file": str(CA_FILE),
        "dns_names": dns_names,
        "ip_addresses": ip_addresses,
        "expires_at": certificate.not_valid_after_utc.isoformat(),
        "tls_enabled": bool(network.get("tls_enabled", False)),
        "tls_verify_server": bool(network.get("tls_verify_server", False)),
        "note": "Browser WSS connections require the certificate SANs to match the hostname you use in the client.",
    }
    INFO_FILE.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    settings = _load_settings()
    _ensure_network_tls_paths(settings)

    private_key = _generate_private_key()
    certificate = _generate_self_signed_certificate(private_key, settings)
    _write_files(private_key, certificate, settings)
    _save_settings(settings)

    print("Generated local TLS materials:")
    print(f"- Certificate: {CERT_FILE}")
    print(f"- Private key: {KEY_FILE}")
    print(f"- CA bundle:   {CA_FILE}")
    print(f"- Metadata:    {INFO_FILE}")
    print()
    print("Next steps:")
    print("1. Set 'tls_enabled' to true in settings.json.")
    print("2. Restart the server and reconnect the web client.")
    print("3. For stricter client verification, set 'tls_verify_server' to true.")


if __name__ == "__main__":
    main()
