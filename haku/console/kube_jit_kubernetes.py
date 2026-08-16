"""Kubernetes adapter for the independent temporary-access reconciler."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from typing import Any, Sequence

from kubernetes_asyncio import client as k8s_client, config as k8s_config
from kubernetes_asyncio.client import ApiClient, RbacAuthorizationV1Api
from kubernetes_asyncio.config.config_exception import ConfigException

from haku.console.kube_jit import (
    MANAGED_BY_LABEL,
    MANAGED_BY_VALUE,
    AccessClient,
    Grant,
    role_binding_manifest,
    role_manifest,
)


@dataclass(frozen=True, slots=True)
class KubernetesAccessClients:
    api: ApiClient
    rbac: RbacAuthorizationV1Api


class KubernetesAccessResources(AccessClient):
    """Owns only lease-named Role/RoleBinding pairs, never unlabelled RBAC objects."""

    def __init__(self, clients: KubernetesAccessClients | None = None) -> None:
        self._clients = clients
        self._lock = asyncio.Lock()

    async def _connected(self) -> KubernetesAccessClients:
        async with self._lock:
            if self._clients is None:
                configuration = k8s_client.Configuration()
                try:
                    k8s_config.load_incluster_config(client_configuration=configuration)
                except ConfigException as error:
                    raise RuntimeError("Kubernetes in-cluster configuration is unavailable") from error
                api = ApiClient(configuration=configuration)
                self._clients = KubernetesAccessClients(api=api, rbac=RbacAuthorizationV1Api(api))
            return self._clients

    async def apply(self, grant: Grant, *, confirmed_until: datetime.datetime) -> None:
        client = (await self._connected()).rbac
        # Role first: a RoleBinding never outlives a failed Role creation for a new lease.
        await _replace_or_create(client.read_namespaced_role, client.create_namespaced_role, client.replace_namespaced_role, grant.role_name, grant.namespace, role_manifest(grant, confirmed_until=confirmed_until))
        await _replace_or_create(client.read_namespaced_role_binding, client.create_namespaced_role_binding, client.replace_namespaced_role_binding, grant.role_binding_name, grant.namespace, role_binding_manifest(grant, confirmed_until=confirmed_until))

    async def delete(self, *, namespace: str, name: str) -> None:
        client = (await self._connected()).rbac
        # Binding first removes the authorization edge before cleaning its policy object.
        for delete in (client.delete_namespaced_role_binding, client.delete_namespaced_role):
            try:
                await delete(name, namespace)
            except k8s_client.ApiException as error:
                if error.status != 404:
                    raise

    async def managed(self, namespaces: Sequence[str]) -> list[dict[str, object]]:
        client = (await self._connected()).rbac
        resources: list[dict[str, object]] = []
        selector = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"
        for namespace in namespaces:
            roles = await client.list_namespaced_role(namespace, label_selector=selector)
            result = await client.list_namespaced_role_binding(namespace, label_selector=selector)
            resources.extend(item.to_dict() for item in roles.items)
            resources.extend(item.to_dict() for item in result.items)
        return resources

    async def aclose(self) -> None:
        if self._clients is not None:
            await self._clients.api.close()
            self._clients = None


async def _replace_or_create(read: Any, create: Any, replace: Any, name: str, namespace: str, body: dict[str, object]) -> None:
    try:
        existing = await read(name, namespace)
    except k8s_client.ApiException as error:
        if error.status != 404:
            raise
        await create(namespace, body)
        return
    body["metadata"]["resourceVersion"] = existing.metadata.resource_version  # type: ignore[index]
    try:
        await replace(name, namespace, body)
    except k8s_client.ApiException as error:
        if error.status != 409:
            raise
