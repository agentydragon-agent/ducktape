"""Tests for K8sTokenStore.reconcile_annotations."""

from unittest.mock import AsyncMock

import pytest_bazel
from kubernetes_asyncio.client import ApiException, V1ObjectMeta, V1Secret

from airlock.oauth.k8s_client import K8sTokenStore


def _store(annotations: dict[str, str] | None) -> tuple[K8sTokenStore, AsyncMock]:
    api = AsyncMock()
    api.read_namespaced_secret.return_value = V1Secret(metadata=V1ObjectMeta(annotations=annotations))
    return K8sTokenStore(api, managed_by="airlock"), api


async def test_reconcile_patches_on_drift() -> None:
    store, api = _store({"reflector/ns": "openclaw-sandbox"})
    await store.reconcile_annotations(
        "plaid-chase-access-token", "airlock", {"reflector/ns": "openclaw-sandbox,plaid-mcp"}
    )
    api.patch_namespaced_secret.assert_awaited_once_with(
        "plaid-chase-access-token",
        "airlock",
        {"metadata": {"annotations": {"reflector/ns": "openclaw-sandbox,plaid-mcp"}}},
    )


async def test_reconcile_noop_when_in_sync() -> None:
    # Configured keys already present (extra unmanaged keys are left alone).
    store, api = _store({"reflector/ns": "openclaw-sandbox,plaid-mcp", "other": "x"})
    await store.reconcile_annotations("s", "airlock", {"reflector/ns": "openclaw-sandbox,plaid-mcp"})
    api.patch_namespaced_secret.assert_not_called()


async def test_reconcile_noop_when_secret_absent() -> None:
    api = AsyncMock()
    api.read_namespaced_secret.side_effect = ApiException(status=404)
    store = K8sTokenStore(api, managed_by="airlock")
    await store.reconcile_annotations("s", "airlock", {"k": "v"})
    api.patch_namespaced_secret.assert_not_called()


async def test_reconcile_noop_when_no_annotations_configured() -> None:
    store, api = _store({})
    await store.reconcile_annotations("s", "airlock", {})
    api.read_namespaced_secret.assert_not_called()
    api.patch_namespaced_secret.assert_not_called()


if __name__ == "__main__":
    pytest_bazel.main()
