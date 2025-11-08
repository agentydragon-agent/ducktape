"""Log collection for Harbor OIDC investigation."""

import asyncio

from ..config import (
    AUTHENTIK_NAMESPACE,
    AUTHENTIK_POSTGRESQL,
    AUTHENTIK_REDIS,
    AUTHENTIK_SERVER,
    AUTHENTIK_WORKER,
    HARBOR_ADMIN_INIT_JOB,
    HARBOR_CORE,
    HARBOR_DATABASE,
    HARBOR_JOBSERVICE,
    HARBOR_NAMESPACE,
    HARBOR_OIDC_CONFIG_JOB,
    HARBOR_PORTAL,
    HARBOR_REDIS,
    HARBOR_REGISTRY,
    HARBOR_TRIVY,
)
from .base import BaseCollector


class LogCollector(BaseCollector):
    """Collector for logs from Harbor and Authentik components."""

    async def collect(self) -> None:
        """Gather all logs from Harbor and Authentik components."""
        self.logger.info("🪵 GATHERING ALL THE LOGS...")

        tasks = []

        # Define all log collection targets
        log_targets = [
            # (type, namespace, name)
            ("deployment", HARBOR_NAMESPACE, HARBOR_CORE),
            ("deployment", HARBOR_NAMESPACE, HARBOR_PORTAL),
            ("deployment", HARBOR_NAMESPACE, HARBOR_JOBSERVICE),
            ("deployment", HARBOR_NAMESPACE, HARBOR_REGISTRY),
            ("deployment", HARBOR_NAMESPACE, HARBOR_TRIVY),
            ("deployment", HARBOR_NAMESPACE, HARBOR_REDIS),
            ("statefulset", HARBOR_NAMESPACE, HARBOR_DATABASE),
            ("job", HARBOR_NAMESPACE, HARBOR_OIDC_CONFIG_JOB),
            ("job", HARBOR_NAMESPACE, HARBOR_ADMIN_INIT_JOB),
            ("deployment", AUTHENTIK_NAMESPACE, AUTHENTIK_SERVER),
            ("deployment", AUTHENTIK_NAMESPACE, AUTHENTIK_WORKER),
            ("deployment", AUTHENTIK_NAMESPACE, AUTHENTIK_POSTGRESQL),
            ("deployment", AUTHENTIK_NAMESPACE, AUTHENTIK_REDIS),
        ]

        for resource_type, namespace, name in log_targets:
            if resource_type in ["deployment", "statefulset"]:
                # Collect current and previous logs for deployments and statefulsets
                tasks.append(
                    self._collect_resource_logs(namespace, name, resource_type)
                )
                tasks.append(
                    self._collect_resource_logs(
                        namespace, name, resource_type, previous=True
                    )
                )
            elif resource_type == "job":
                tasks.append(self._collect_job_logs(namespace, name))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _collect_resource_logs(
        self,
        namespace: str,
        resource_name: str,
        resource_type: str,
        previous: bool = False,
    ) -> None:
        """Collect logs for a resource (deployment/statefulset)."""
        if resource_type == "deployment":
            logs = await self.k8s.get_deployment_logs(
                namespace, resource_name, previous
            )
        elif resource_type == "statefulset":
            logs = await self.k8s.get_statefulset_logs(
                namespace, resource_name, previous
            )
        else:
            return

        suffix = "-previous" if previous else ""
        self.write_output(
            logs,
            f"logs/{resource_name}{suffix}.log",
            f"{resource_name} logs{' (previous)' if previous else ''}",
        )

    async def _collect_job_logs(self, namespace: str, job: str) -> None:
        """Collect logs for a job."""
        logs = await self.k8s.get_job_logs(namespace, job)
        self.write_output(logs, f"logs/{job}.log", f"{job} logs")
