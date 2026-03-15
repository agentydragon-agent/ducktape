"""K8s-based secrets setup for Claude Code sessions.

Reads secrets from Kubernetes Secrets in the cluster using a ServiceAccount token,
and builds a kubeconfig for kubectl access.

Config mapping (secret name, data keys, env vars) is defined in
.claude_hooks/config.yaml under the k8s_secrets section.
"""

import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from kubernetes import client as k8s_client
from kubernetes.client import Configuration, CoreV1Api

from devinfra.claude.hook_config import HookConfig

logger = logging.getLogger(__name__)


@dataclass
class K8sSecretsResult:
    """Result of k8s secrets setup."""

    env_vars: dict[str, str] = field(default_factory=dict)
    kubeconfig_path: Path | None = None
    buildbuddy_api_key: str | None = None
    otel_bearer_token: str | None = None


def _build_kubeconfig(token: str, server: str, service_account: str, namespace: str, ca_path: Path | None) -> dict:
    """Build kubeconfig dict for kubectl CLI use."""
    cluster_config: dict[str, str] = {"server": server}
    if ca_path and ca_path.exists():
        ca_pem = ca_path.read_text()
        cluster_config["certificate-authority-data"] = base64.b64encode(ca_pem.encode()).decode()

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


def setup_k8s_secrets(
    token: str, session_dir: Path, combined_ca_path: Path | None, config: HookConfig, proxy: str | None = None
) -> K8sSecretsResult:
    """Read secrets from k8s and write kubeconfig.

    Uses the kubernetes Python client with a Bearer token to read secrets
    from the configured namespace, maps data keys to env var names, and
    writes a kubeconfig file for kubectl CLI use.

    In web mode, pass proxy="http://localhost:<port>" to route through the
    auth proxy, which adds Proxy-Authorization for the upstream egress proxy.
    """
    result = K8sSecretsResult()
    if not config.k8s or not config.k8s_secrets:
        raise ValueError(f"k8s and k8s_secrets config sections are required, got {config.k8s=}, {config.k8s_secrets=}")
    k8s_cfg = config.k8s
    secrets_cfg = config.k8s_secrets

    # Configure k8s client
    client_config = Configuration()
    client_config.host = k8s_cfg.server
    client_config.api_key = {"authorization": f"Bearer {token}"}
    if combined_ca_path and combined_ca_path.exists():
        client_config.ssl_ca_cert = str(combined_ca_path)
    else:
        client_config.verify_ssl = True
    if proxy:
        client_config.proxy = proxy

    api = CoreV1Api(k8s_client.ApiClient(client_config))

    # Read each secret and map to env vars
    for entry in secrets_cfg.secrets:
        try:
            secret = api.read_namespaced_secret(entry.name, secrets_cfg.namespace)
        except k8s_client.ApiException as e:
            logger.warning("Failed to read secret %s/%s: %s", secrets_cfg.namespace, entry.name, e.reason)
            continue

        if not secret.data:
            logger.warning("Secret %s/%s has no data", secrets_cfg.namespace, entry.name)
            continue

        for data_key, env_var in entry.data.items():
            if data_key not in secret.data:
                logger.warning("Key %r not found in secret %s/%s", data_key, secrets_cfg.namespace, entry.name)
                continue
            if env_var in result.env_vars:
                raise ValueError(f"Duplicate env var {env_var!r}")
            value = base64.b64decode(secret.data[data_key]).decode()
            result.env_vars[env_var] = value
            logger.info("Mapped %s/%s[%s] -> %s", secrets_cfg.namespace, entry.name, data_key, env_var)

    # Fetch BuildBuddy API key (internal use only, not exported as env var)
    if secrets_cfg.buildbuddy_api_key:
        ref = secrets_cfg.buildbuddy_api_key
        try:
            bb_secret = api.read_namespaced_secret(ref.secret_name, secrets_cfg.namespace)
            if bb_secret.data and ref.data_key in bb_secret.data:
                result.buildbuddy_api_key = base64.b64decode(bb_secret.data[ref.data_key]).decode()
                logger.info(
                    "BuildBuddy API key read from %s/%s[%s]", secrets_cfg.namespace, ref.secret_name, ref.data_key
                )
        except k8s_client.ApiException as e:
            logger.warning("Failed to read BuildBuddy API key: %s", e.reason)

    # Fetch OTEL bearer token (used internally, not exported as env var)
    if secrets_cfg.otel_bearer_token:
        ref = secrets_cfg.otel_bearer_token
        try:
            otel_secret = api.read_namespaced_secret(ref.secret_name, secrets_cfg.namespace)
            if otel_secret.data and ref.data_key in otel_secret.data:
                result.otel_bearer_token = base64.b64decode(otel_secret.data[ref.data_key]).decode()
                logger.info(
                    "OTEL bearer token read from %s/%s[%s]", secrets_cfg.namespace, ref.secret_name, ref.data_key
                )
        except k8s_client.ApiException as e:
            logger.warning("Failed to read OTEL bearer token: %s", e.reason)

    # Write kubeconfig
    kubeconfig = _build_kubeconfig(token, k8s_cfg.server, k8s_cfg.service_account, k8s_cfg.namespace, combined_ca_path)
    kubeconfig_path = session_dir / "kubeconfig"
    kubeconfig_path.write_text(yaml.dump(kubeconfig, default_flow_style=False))
    kubeconfig_path.chmod(0o600)
    result.kubeconfig_path = kubeconfig_path
    result.env_vars["KUBECONFIG"] = str(kubeconfig_path)
    logger.info("Kubeconfig written to %s", kubeconfig_path)

    return result
