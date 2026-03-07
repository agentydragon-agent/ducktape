"""Kubeconfig setup for Claude Code sessions.

Builds a kubeconfig file from typed secret fields and writes it to a file,
updating the env_vars dict to set the KUBECONFIG path.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class KubeconfigSecret(BaseModel):
    """Typed kubeconfig secret stored in kubeconfig.age.

    The API endpoint uses a publicly-trusted TLS certificate (via kube-api-proxy),
    so no cluster CA is needed. The proxy CA (if behind a TLS-inspecting proxy)
    is injected separately by setup_kubeconfig().
    """

    type: Literal["kubeconfig"] = "kubeconfig"
    server: str
    token: str


def setup_kubeconfig(
    session_dir: Path, secret: KubeconfigSecret, env_vars: dict[str, str], proxy_ca_pem: str | None = None
) -> Path:
    """Build and write a kubeconfig from typed secret fields.

    The API endpoint has a publicly-trusted TLS cert, so no cluster CA is needed.
    If proxy_ca_pem is provided (TLS-inspecting proxy), it is set as the CA so
    kubectl trusts the proxy's certificate.

    Sets env_vars["KUBECONFIG"] so the path is exported to the shell session.
    """
    cluster_config: dict[str, str] = {"server": secret.server}
    if proxy_ca_pem:
        cluster_config["certificate-authority-data"] = base64.b64encode(proxy_ca_pem.encode()).decode()

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"cluster": cluster_config, "name": "cluster"}],
        "contexts": [
            {
                "context": {"cluster": "cluster", "namespace": "claude-sandbox", "user": "claude-code-web"},
                "name": "claude-code-web",
            }
        ],
        "current-context": "claude-code-web",
        "users": [{"name": "claude-code-web", "user": {"token": secret.token}}],
    }

    kubeconfig_path = session_dir / "kubeconfig"
    kubeconfig_path.write_text(yaml.dump(kubeconfig, default_flow_style=False))
    kubeconfig_path.chmod(0o600)

    env_vars["KUBECONFIG"] = str(kubeconfig_path)
    logger.info("Kubeconfig written to %s (proxy_ca=%s)", kubeconfig_path, proxy_ca_pem is not None)
    return kubeconfig_path
