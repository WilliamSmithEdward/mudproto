from pathlib import Path
import importlib.util


def _load_tls_generator_module():
    project_root = Path(__file__).resolve().parents[3]
    module_path = project_root / "mudproto_server" / "configuration" / "server" / "encryption" / "generate_encryption_files.py"
    spec = importlib.util.spec_from_file_location("mudproto_tls_generator", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_certificate_subject_alt_names_includes_configured_public_hosts() -> None:
    tls_generator = _load_tls_generator_module()
    settings = {
        "network": {
            "host": "0.0.0.0",
            "tls_dns_names": ["williamsmithe.com", "localhost"],
            "tls_ip_addresses": ["172.233.152.179", "127.0.0.1", "::1"],
        }
    }

    dns_names, ip_addresses = tls_generator._resolve_certificate_subject_alt_names(settings)

    assert "williamsmithe.com" in dns_names
    assert "localhost" in dns_names
    assert "172.233.152.179" in ip_addresses
    assert "127.0.0.1" in ip_addresses
