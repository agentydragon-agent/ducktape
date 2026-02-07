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

    host/port: How the Docker daemon (on the host) reaches the registry proxy.
    proxy_url: HTTP URL for tag resolution (HEAD /v2/{repo}/manifests/{ref}).
    """

    host: str
    port: int

    @property
    def proxy_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def build_oci_reference(self, agent_type: AgentType, digest: str) -> str:
        """Build full OCI reference (host:port/repository@digest)."""
        repository = str(agent_type)
        return f"{self.host}:{self.port}/{repository}@{digest}"

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
        return f"{self.host}:{self.port}/{image_ref}"


def get_registry_proxy_config() -> RegistryProxyConfig:
    """Get registry configuration from environment variables.

    Environment variables:
        PROPS_REGISTRY_HOST: Host for Docker daemon to reach registry proxy (default: 127.0.0.1)
        PROPS_REGISTRY_PORT: Port for Docker daemon to reach registry proxy (default: 8000)
    """
    return RegistryProxyConfig(
        host=os.environ.get("PROPS_REGISTRY_HOST", "127.0.0.1"), port=int(os.environ.get("PROPS_REGISTRY_PORT", "8000"))
    )


def is_digest(ref: str) -> bool:
    """Check if a reference is a digest (sha256:...) vs a tag."""
    return bool(re.match(r"^(sha256|sha384|sha512):[a-f0-9]+$", ref))
