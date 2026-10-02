"""Real Kubernetes clients against a local API server, with no integration-app fixtures."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from kubernetes_asyncio import client as k8s_client

from agentplane.sandbox_service.inventory import SandboxInventory
from agentplane.sandbox_service.client import SandboxServiceClient
from agentplane.sandbox_service.destinations import DestinationResolver
from agentplane.sandbox_service.grpc_api import Resources
from agentplane.sandbox_service.testing.grpc_service import service_client
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from agentplane.sandbox_service.kubernetes_views import MANAGED_LABEL
from agentplane.testing.fake_apiserver import SANDBOX_NAMESPACE, FakeApiServer, TokenVerdict, fake_apiserver, pod_for
from util.agent_sandbox import SANDBOX_API, SANDBOXES_PLURAL
from util.kubernetes import CustomObjectsClient

SANDBOX = "test-runner"
SANDBOX_UID = UUID("40e373bd-2742-43de-8d1c-1ef97c4d4801")
ACCOUNT = "test-runner-account"


@dataclass
class Cluster:
    fake: FakeApiServer
    api: k8s_client.ApiClient
    inventory: SandboxInventory


@asynccontextmanager
async def kubernetes() -> AsyncIterator[Cluster]:
    async with fake_apiserver() as fake:
        fake.put(
            SANDBOXES_PLURAL,
            {
                "apiVersion": SANDBOX_API.api_version,
                "kind": "Sandbox",
                "metadata": {
                    "name": SANDBOX,
                    "namespace": SANDBOX_NAMESPACE,
                    "uid": str(SANDBOX_UID),
                    "creationTimestamp": "2026-09-01T11:00:00Z",
                    "labels": {MANAGED_LABEL: "true"},
                },
                "spec": {"podTemplate": {"spec": {"serviceAccountName": ACCOUNT}}},
            },
        )
        pod = pod_for(fake, SANDBOX, pod_uid="test-pod-uid", ip="127.0.0.1")
        pod["spec"] = {
            "serviceAccountName": ACCOUNT,
            "containers": [{"name": "runner", "image": "registry.test/runner:unused"}],
        }
        pod["status"] |= {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}
        fake.pods[SANDBOX] = pod
        configuration = k8s_client.Configuration(host=f"http://127.0.0.1:{fake.port}")
        async with k8s_client.ApiClient(configuration) as api:
            yield Cluster(
                fake,
                api,
                SandboxInventory(
                    namespace=SANDBOX_NAMESPACE,
                    custom_objects=cast(CustomObjectsClient, k8s_client.CustomObjectsApi(api)),
                    core_v1=k8s_client.CoreV1Api(api),
                ),
            )


@asynccontextmanager
async def authenticated_service(cluster: Cluster, runner_port: int, token_file: Path) -> AsyncIterator[SandboxServiceClient]:
    manager = ServiceAccountRef(namespace=SANDBOX_NAMESPACE, name="test-app")
    token, audience = "test-app-service-token", "test-app-sandbox-service"
    token_file.write_text(token)
    cluster.fake.tokens[token] = TokenVerdict(
        username=f"system:serviceaccount:{manager.namespace}:{manager.name}",
        pod_name="test-app-pod", pod_uid="test-app-pod-uid", audiences=(audience,),
    )
    resources = Resources(
        principals=WorkloadPrincipalResolver(
            authentication=k8s_client.AuthenticationV1Api(cluster.api), audience=audience,
            allowed_service_account_namespaces={SANDBOX_NAMESPACE},
        ),
        destinations=DestinationResolver(cluster.inventory, k8s_client.CoreV1Api(cluster.api), runner_port, frozenset({manager})),
        manager_accounts=frozenset({manager}), platform_instructions="Backend guidance for app-launched sessions.",
        follow_lease_s=1,
    )
    async with service_client(resources, token_file) as client:
        yield client
