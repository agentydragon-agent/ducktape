"""Standalone Sandbox Service entry point. Kubernetes owns inventory; runners own session logs."""

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

import uvicorn
from kubernetes_asyncio import client as k8s_client, config as k8s_config
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from agentplane.sandbox_service.api import SessionResources, create_app
from agentplane.sandbox_service.destinations import DestinationResolver
from agentplane.sandbox_service.instructions import resolved_agent_instructions
from agentplane.sandbox_service.inventory import SandboxInventory
from agentplane.subjects import ServiceAccountRef
from agentplane.workload_auth.http import WorkloadPrincipalAuthenticator
from agentplane.workload_auth.principal import WorkloadPrincipalResolver
from util.kubernetes import CustomObjectsClient


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTPLANE_SANDBOX_SERVICE_", cli_parse_args=True, cli_kebab_case=True
    )

    sandbox_namespace: str = Field(min_length=1)
    allowed_service_account_namespaces: frozenset[str] = Field(min_length=1)
    trusted_accounts: frozenset[ServiceAccountRef] = Field(default_factory=frozenset)
    manager_accounts: frozenset[ServiceAccountRef] = Field(default_factory=frozenset)
    agent_instructions: str | None = None
    agent_egress_api_url: str | None = None
    agent_actions_service_url: str | None = None
    lifecycle_timeout_s: float = Field(default=300, gt=0)
    token_audience: str = "agentplane-egress"
    runner_port: int = Field(default=7000, ge=1, le=65535)
    admission_timeout_s: float = Field(default=15, gt=0, le=60)
    follow_lease_s: float = Field(default=30, gt=0, le=60)
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    kubeconfig: Path | None = None

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)


async def serve(settings: Settings) -> None:
    platform_instructions = (
        resolved_agent_instructions(
            settings.agent_instructions,
            egress_api_url=settings.agent_egress_api_url,
            actions_service_url=settings.agent_actions_service_url,
        )
        if settings.manager_accounts else None
    )
    configuration = k8s_client.Configuration()
    if settings.kubeconfig is None:
        k8s_config.load_incluster_config(client_configuration=configuration)
    else:
        await k8s_config.load_kube_config(config_file=str(settings.kubeconfig), client_configuration=configuration)
    async with k8s_client.ApiClient(configuration) as api:
        core = k8s_client.CoreV1Api(api)
        inventory = SandboxInventory(
            namespace=settings.sandbox_namespace,
            core_v1=core,
            custom_objects=cast(CustomObjectsClient, k8s_client.CustomObjectsApi(api)),
        )
        authenticate = WorkloadPrincipalAuthenticator(
            WorkloadPrincipalResolver(
                authentication=k8s_client.AuthenticationV1Api(api),
                audience=settings.token_audience,
                allowed_service_account_namespaces=settings.allowed_service_account_namespaces,
            )
        )
        app = create_app(
            SessionResources(
                authenticate=authenticate,
                destinations=DestinationResolver(inventory, core, settings.runner_port, settings.trusted_accounts),
                admission_timeout_s=settings.admission_timeout_s,
                follow_lease_s=settings.follow_lease_s,
                manager_accounts=settings.manager_accounts,
                platform_instructions=platform_instructions,
                lifecycle_timeout_s=settings.lifecycle_timeout_s,
            )
        )
        await uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, access_log=False)).serve()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # TokenReview responses echo their bearer. Do not log the generated client's wire bodies.
    logging.getLogger("kubernetes_asyncio.client.rest").setLevel(logging.INFO)
    asyncio.run(serve(Settings()))


if __name__ == "__main__":
    main()
