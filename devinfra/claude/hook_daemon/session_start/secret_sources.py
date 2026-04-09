"""Secrets resolution and kubeconfig generation for Claude Code sessions.

Resolves secrets from SOPS-encrypted YAML files and writes kubeconfig
for kubectl access using the SOPS-resolved k8s token.
"""

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from devinfra.claude.hook_daemon.config import K8sConfig, SecretSource
from devinfra.claude.sops_decrypt import decrypt_sops_yaml

logger = logging.getLogger(__name__)


@dataclass
class SecretsResult:
    """Resolved secrets with explicit named fields."""

    k8s_token: str | None = None
    buildbuddy_api_key: str | None = None
    github_token: str | None = None
    kubeconfig_path: Path | None = None


def resolve_secret(source: SecretSource, *, project_dir: Path) -> str | None:
    """Resolve a single secret from its SOPS source config."""
    decrypted = decrypt_sops_yaml(project_dir / source.sops_file)
    return decrypted.get(source.key)


def build_kubeconfig(
    token: str, server: str, service_account: str, namespace: str, ca_path: Path | None, proxy_url: str | None
) -> dict:
    """Build kubeconfig dict for kubectl CLI use."""
    cluster_config: dict[str, str] = {"server": server}
    if ca_path and ca_path.exists():
        ca_pem = ca_path.read_text()
        cluster_config["certificate-authority-data"] = base64.b64encode(ca_pem.encode()).decode()
    if proxy_url:
        cluster_config["proxy-url"] = proxy_url

    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"cluster": cluster_config, "name": "cluster"}],
        "contexts": [
            {
                "context": {"cluster": "cluster", "namespace": namespace, "user": service_account},
                "name": service_account,
            }
        ],
        "current-context": service_account,
        "users": [{"name": service_account, "user": {"token": token}}],
    }


def write_kubeconfig(
    token: str, k8s_cfg: K8sConfig, session_dir: Path, combined_ca_path: Path | None, proxy_url: str | None
) -> Path:
    """Write kubeconfig file and return its path."""
    kubeconfig = build_kubeconfig(
        token, k8s_cfg.server, k8s_cfg.service_account, k8s_cfg.namespace, combined_ca_path, proxy_url=proxy_url
    )
    kubeconfig_path = session_dir / "kubeconfig"
    kubeconfig_path.write_text(yaml.dump(kubeconfig, default_flow_style=False))
    kubeconfig_path.chmod(0o600)
    logger.info("Kubeconfig written to %s", kubeconfig_path)
    return kubeconfig_path
