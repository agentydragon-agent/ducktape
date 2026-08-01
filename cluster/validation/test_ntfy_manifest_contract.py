"""Focused contract over the deployed Flux ntfy Provider Secret."""

from __future__ import annotations

from pathlib import Path

import pytest_bazel
import yaml

from util.bazel.runfiles import get_required_path

_NTFY_SECRET = "_main/cluster/k8s/flux-webhook/ntfy-webhook.sops.yaml"


def test_ntfy_provider_headers_parse_as_yaml_map() -> None:
    """notification-controller parses Provider secret `headers` as a YAML string map."""
    secret_path: Path = get_required_path(_NTFY_SECRET)
    secret = yaml.safe_load(secret_path.read_text())
    headers = yaml.safe_load(secret["stringData"]["headers"])

    assert isinstance(headers, dict)
    assert headers
    assert all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items())


if __name__ == "__main__":
    pytest_bazel.main()
