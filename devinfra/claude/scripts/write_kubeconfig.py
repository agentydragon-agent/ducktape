"""Materialize a client-certificate kubeconfig from SOPS-encrypted secrets.

Standalone repo-specific script (not part of the generic hook daemon).
Invoked as a profile background command during SessionStart and by the
claude-sandbox-kubectl MCP server script.

Usage:
    python3 "$CLAUDE_PROJECT_DIR/devinfra/claude/scripts/write_kubeconfig.py" \\
        [OPTIONS] OUTPUT_PATH

Requires CLAUDE_PROJECT_DIR (to locate secrets/claude-web-k8s-cert.yaml)
and SOPS_AGE_KEY (for sops decryption) in the environment.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

_K8S_CERT_SOPS_PATH = "secrets/claude-web-k8s-cert.yaml"
_K8S_CA_PATH = "secrets/k8s-ca.crt"
_SYSTEM_CA_BUNDLE = Path("/etc/ssl/certs/ca-certificates.crt")

_DEFAULT_SERVER = "https://api.allegedly.works"
_DEFAULT_USER = "claude-code-web"
_DEFAULT_NAMESPACE = "claude-sandbox"


def _sops_extract(sops_path: Path, key: str) -> str:
    result = subprocess.run(["sops", "-d", "--extract", f'["{key}"]', str(sops_path)], capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"sops -d --extract {key} {sops_path} failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    value = result.stdout.decode(errors="replace").strip()
    if not value:
        raise RuntimeError(f"sops decrypted empty {key} from {sops_path}")
    return value


def decrypt_client_cert(project_dir: Path) -> tuple[str, str]:
    """Return (client_cert_pem, client_key_pem) from the SOPS-encrypted file."""
    sops_path = project_dir / _K8S_CERT_SOPS_PATH
    if not sops_path.is_file():
        raise RuntimeError(f"k8s cert SOPS file not found: {sops_path}")
    client_cert = _sops_extract(sops_path, "client_cert")
    client_key = _sops_extract(sops_path, "client_key")
    return client_cert, client_key


def build_kubeconfig(
    client_cert: str,
    client_key: str,
    server: str,
    user: str,
    namespace: str,
    ca_data: bytes | None,
    proxy_url: str | None,
) -> dict:
    cluster_config: dict[str, str] = {"server": server}
    if ca_data:
        cluster_config["certificate-authority-data"] = base64.b64encode(ca_data).decode()
    if proxy_url:
        cluster_config["proxy-url"] = proxy_url

    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"cluster": cluster_config, "name": "cluster"}],
        "contexts": [{"context": {"cluster": "cluster", "namespace": namespace, "user": user}, "name": user}],
        "current-context": user,
        "users": [
            {
                "name": user,
                "user": {
                    "client-certificate-data": base64.b64encode(client_cert.encode()).decode(),
                    "client-key-data": base64.b64encode(client_key.encode()).decode(),
                },
            }
        ],
    }


def write_kubeconfig_file(kubeconfig: dict, output_path: Path) -> None:
    """Atomic 0o600 write — never clobbers.

    If the file exists and its parsed YAML differs from `kubeconfig`, raises.
    A match is a no-op; a missing file is written fresh.
    """
    if output_path.exists():
        existing_raw = output_path.read_text()
        try:
            existing = yaml.safe_load(existing_raw)
        except yaml.YAMLError as e:
            raise RuntimeError(f"refusing to overwrite {output_path}: existing file is not valid YAML ({e})") from e
        if existing != kubeconfig:
            raise RuntimeError(
                f"refusing to overwrite {output_path}: existing kubeconfig differs from the one we'd write"
            )
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(kubeconfig, default_flow_style=False, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(serialized)
        tmp_path.replace(output_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write a k8s client-certificate kubeconfig from SOPS secrets.")
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--server", default=_DEFAULT_SERVER)
    parser.add_argument("--user", default=_DEFAULT_USER)
    parser.add_argument("--namespace", default=_DEFAULT_NAMESPACE)
    args = parser.parse_args(argv)

    project_dir_str = os.environ.get("CLAUDE_PROJECT_DIR")
    if not project_dir_str:
        print("CLAUDE_PROJECT_DIR not set", file=sys.stderr)
        sys.exit(1)
    project_dir = Path(project_dir_str)

    client_cert, client_key = decrypt_client_cert(project_dir)

    # The API server cert is signed by the cluster CA (not publicly trusted).
    # On Claude Code web, traffic goes through Anthropic's TLS-inspecting proxy
    # whose CA is in the system bundle. Combine both so the chain validates in
    # all environments.
    ca_parts: list[bytes] = []
    cluster_ca = project_dir / _K8S_CA_PATH
    if cluster_ca.is_file():
        ca_parts.append(cluster_ca.read_bytes())
    if _SYSTEM_CA_BUNDLE.is_file():
        ca_parts.append(_SYSTEM_CA_BUNDLE.read_bytes())
    ca_data = b"\n".join(ca_parts) if ca_parts else None

    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )

    kubeconfig = build_kubeconfig(
        client_cert=client_cert,
        client_key=client_key,
        server=args.server,
        user=args.user,
        namespace=args.namespace,
        ca_data=ca_data,
        proxy_url=proxy_url,
    )
    write_kubeconfig_file(kubeconfig, args.output_path)
    ca_sources = []
    if cluster_ca.is_file():
        ca_sources.append("cluster")
    if _SYSTEM_CA_BUNDLE.is_file():
        ca_sources.append("system")
    print(
        f"wrote {args.output_path} — server={args.server} ca={'+'.join(ca_sources) or 'none'} "
        f"proxy={'set' if proxy_url else 'unset'}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
