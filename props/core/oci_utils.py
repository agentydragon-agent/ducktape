"""Utilities for OCI image operations.

Handles:
- Registry configuration (RegistryProxyConfig)
- OCI reference building
- Digest detection
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from props.core.agent_types import AgentType

logger = logging.getLogger(__name__)

# Builtin image tag - used by all Bazel oci_push targets
BUILTIN_TAG = "latest"


@dataclass(frozen=True)
class RegistryProxyConfig:
    """Registry proxy configuration for image resolution and OCI references.

    The registry proxy is part of the props backend - it proxies OCI API requests
    to an upstream registry and records agent_definitions on push.

    host/port: How the backend reaches the registry proxy (HTTP tag resolution).
    pull_host/pull_port: How the container runtime (kubelet/Docker) pulls images.
      Defaults to host/port when not set. Needed in k8s where the backend resolves
      the service name (e.g. "props") via cluster DNS, but the kubelet can't.
    """

    host: str
    port: int
    pull_host: str | None = None
    pull_port: int | None = None

    @property
    def proxy_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _pull_authority(self) -> str:
        """Host:port string for image references (what the container runtime pulls from)."""
        h = self.pull_host or self.host
        p = self.pull_port if self.pull_host else self.port
        if p is None or p in (443, 80):
            return h
        return f"{h}:{p}"

    def build_oci_reference(self, agent_type: AgentType, digest: str) -> str:
        """Build full OCI reference (host:port/repository@digest)."""
        repository = str(agent_type)
        return f"{self._pull_authority()}/{repository}@{digest}"

    def normalize_image_ref(self, image_ref: str) -> str:
        """Normalize image reference, adding registry if needed.

        Examples:
            "critic:latest" -> "localhost:8000/critic:latest"
            "localhost:8000/critic:latest" -> "localhost:8000/critic:latest"
            "sha256:abc..." -> "sha256:abc..." (digest refs unchanged)
        """
        if image_ref.startswith("sha256:"):
            return image_ref
        if "/" in image_ref and ":" in image_ref.split("/")[0]:
            return image_ref
        authority = self._pull_authority()
        return f"{authority}/{image_ref}"


def get_registry_proxy_config() -> RegistryProxyConfig:
    """Get registry configuration from environment variables.

    Environment variables:
        PROPS_REGISTRY_HOST: Host for backend to reach registry proxy (default: 127.0.0.1)
        PROPS_REGISTRY_PORT: Port for backend to reach registry proxy (default: 8000)
        PROPS_REGISTRY_PULL_HOST: Host for container runtime image pulls (default: PROPS_REGISTRY_HOST)
        PROPS_REGISTRY_PULL_PORT: Port for container runtime image pulls (default: PROPS_REGISTRY_PORT)
    """
    pull_host = os.environ.get("PROPS_REGISTRY_PULL_HOST") or None
    pull_port_str = os.environ.get("PROPS_REGISTRY_PULL_PORT")
    pull_port = int(pull_port_str) if pull_port_str else None
    return RegistryProxyConfig(
        host=os.environ.get("PROPS_REGISTRY_HOST", "127.0.0.1"),
        port=int(os.environ.get("PROPS_REGISTRY_PORT", "8000")),
        pull_host=pull_host,
        pull_port=pull_port,
    )


def is_digest(ref: str) -> bool:
    """Check if a reference is a digest (sha256:...) vs a tag."""
    return bool(re.match(r"^(sha256|sha384|sha512):[a-f0-9]+$", ref))
