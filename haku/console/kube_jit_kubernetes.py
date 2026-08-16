"""Kubernetes adapter for the Console's namespace RoleBinding lease reconciler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubernetes_asyncio.client import ApiClient, RbacAuthorizationV1Api
from kubernetes_asyncio.config.config_exception import ConfigException

from haku.console.kube_jit import MANAGED_BY_LABEL, MANAGED_BY_VALUE, Grant, RoleBindingClient, role_binding_manifest


@dataclass(frozen=True, slots=True)
class KubernetesRoleBindingClients:
    api: ApiClient
    rbac: RbacAuthorizationV1Api


class KubernetesRoleBindings(RoleBindingClient):
    """Idempotently project lease records into only labelled namespace RoleBindings."""

    def __init__(self, clients: KubernetesRoleBindingClients | None = None) -> None:
        self._clients = clients
        self._lock = asyncio.Lock()

    async def _connected(self) -> KubernetesRoleBindingClients:
        async with self._lock:
            if self._clients is None:
                configuration = k8s_client.Configuration()
                try:
                    k8s_config.load_incluster_config(client_configuration=configuration)
                except ConfigException as error:
                    raise RuntimeError("Kubernetes in-cluster configuration is unavailable") from error
                api = ApiClient(configuration=configuration)
                self._clients = KubernetesRoleBindingClients(api=api, rbac=RbacAuthorizationV1Api(api))
            return self._clients

    async def apply(self, grant: Grant, *, confirmed_until) -> None:  # type: ignore[no-untyped-def]
        client = (await self._connected()).rbac
        body = role_binding_manifest(grant, confirmed_until=confirmed_until)
        try:
            existing = await client.read_namespaced_role_binding(grant.role_binding_name, grant.namespace)
        except k8s_client.ApiException as error:
            if error.status != 404:
                raise
            await client.create_namespaced_role_binding(grant.namespace, body)
            return
        # Replace makes the managed object exact: stale subjects, role refs, labels, or annotations
        # cannot survive a later profile revision. resourceVersion avoids clobbering a concurrent
        # trusted operator edit; next reconciliation retries the complete desired state.
        body["metadata"]["resourceVersion"] = existing.metadata.resource_version  # type: ignore[index]
        try:
            await client.replace_namespaced_role_binding(grant.role_binding_name, grant.namespace, body)
        except k8s_client.ApiException as error:
            if error.status != 409:
                raise

    async def delete(self, *, namespace: str, name: str) -> None:
        client = (await self._connected()).rbac
        try:
            await client.delete_namespaced_role_binding(name, namespace)
        except k8s_client.ApiException as error:
            if error.status != 404:
                raise

    async def managed(self, namespaces: list[str] | tuple[str, ...]) -> list[dict[str, object]]:
        client = (await self._connected()).rbac
        bindings: list[dict[str, object]] = []
        selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
        for namespace in namespaces:
            result = await client.list_namespaced_role_binding(namespace, label_selector=selector)
            bindings.extend(item.to_dict(serialize=True) for item in result.items)
        return bindings

    async def aclose(self) -> None:
        if self._clients is not None:
            await self._clients.api.close()
            self._clients = None
