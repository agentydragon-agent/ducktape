"""Diagnostics collection for Harbor OIDC investigation."""

from datetime import datetime
import json

import aiohttp

from ..config import (
    HARBOR_ADMIN_PASSWORD_KEY,
    HARBOR_CORE_POD,
    HARBOR_HOST,
    HARBOR_NAMESPACE,
    HARBOR_OIDC_SECRET,
    OIDC_LOGIN_CURL_CMD,
)
from .base import BaseCollector


class DiagnosticsCollector(BaseCollector):
    """Collector for diagnostics and version information."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_password = None

    async def collect(self) -> None:
        """Collect diagnostics."""
        await self.collect_harbor_oidc_diagnostics()
        await self.collect_harbor_version_info()

    async def collect_harbor_oidc_diagnostics(self) -> None:
        """Collect specific diagnostics for Harbor OIDC 404 issue."""
        self.logger.info("🔍 COLLECTING HARBOR OIDC DIAGNOSTICS...")

        # Run diagnostic commands in harbor-core
        diagnostic_commands = [
            (
                "env | grep -E 'AUTH|OIDC|LOG'",
                "diagnostics/harbor-env.txt",
                "Harbor environment",
            ),
            (
                OIDC_LOGIN_CURL_CMD,
                "diagnostics/internal-oidc-test.txt",
                "Internal OIDC test",
            ),
        ]

        self._run_pod_commands(HARBOR_NAMESPACE, HARBOR_CORE_POD, diagnostic_commands)

        # Get recent pod restart info
        self._collect_pod_restart_info(
            HARBOR_NAMESPACE,
            "component=core",
            "diagnostics/harbor-restarts.txt",
            "Harbor restart info",
        )

    async def collect_harbor_version_info(self) -> None:
        """Collect detailed Harbor version and build information."""
        self.logger.info("📦 COLLECTING DETAILED HARBOR VERSION INFO...")

        version_info = []

        # Get admin password from secret
        self._ensure_admin_password()

        api_endpoints = [
            (f"https://{HARBOR_HOST}/api/version", "API Version"),
            (f"https://{HARBOR_HOST}/api/v2.0/systeminfo", "SystemInfo"),
        ]

        try:
            async with aiohttp.ClientSession() as session:
                auth = aiohttp.BasicAuth("admin", self.admin_password)
                for url, desc in api_endpoints:
                    try:
                        async with session.get(url, auth=auth, ssl=False) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if "systeminfo" in url:
                                    version_info.append(
                                        f"{desc} Version: {data.get('harbor_version', 'unknown')}"
                                    )
                                else:
                                    version_info.append(
                                        f"{desc} Response: {json.dumps(data, indent=2)}"
                                    )
                    except Exception as e:
                        version_info.append(f"Failed to get {desc}: {e}")
        except Exception as e:
            version_info.append(f"Failed to create session: {e}")

        # Get image versions from deployments
        deployments = self.k8s.apps_v1.list_namespaced_deployment(HARBOR_NAMESPACE)
        image_info = []
        for dep in deployments.items:
            if dep.metadata.name.startswith("harbor-"):
                for container in dep.spec.template.spec.containers:
                    image_info.append(
                        f"{dep.metadata.name}/{container.name}: {container.image}"
                    )

        # Try to get version from harbor-core binary
        core_pod = self.k8s._get_first_pod_by_component(HARBOR_NAMESPACE, "core")
        if core_pod:
            # Try various version commands
            version_cmds = [
                (["harbor_core", "--version"], None, "Binary version"),
                ("harbor_core --version 2>&1 || true", None, "Binary version (alt)"),
                ("ls -la /harbor/ 2>&1 || true", None, "Harbor directory"),
                ("cat /harbor/VERSION 2>&1 || true", None, "VERSION file"),
                (
                    "cat /harbor/GIT_COMMIT 2>&1 || echo 'No git info'",
                    None,
                    "Git commit",
                ),
            ]

            # Use _run_pod_commands but capture results
            for cmd, _, description in version_cmds:
                try:
                    cmd_to_run = ["sh", "-c", cmd] if isinstance(cmd, str) else cmd
                    result = self.k8s.exec_in_pod(
                        HARBOR_NAMESPACE, core_pod, cmd_to_run
                    )
                    if result:
                        version_info.append(f"{description}: {result}")
                except Exception:
                    pass

        # Write all version info
        all_version_info = "\n".join(
            [
                "=== DETAILED HARBOR VERSION INFORMATION ===",
                "\n--- API Version Info ---",
                "\n".join(version_info),
                "\n\n--- Container Images ---",
                "\n".join(image_info),
                f"\n\n--- Collection Timestamp: {datetime.utcnow().isoformat()} ---",
            ]
        )
        self.write_output(
            all_version_info,
            "versions/harbor-detailed-versions.txt",
            "Harbor Detailed Version Info",
        )

    def _run_pod_commands(
        self, namespace: str, pod: str, commands: list[tuple[str, str, str]]
    ) -> None:
        """Run multiple commands in a pod and save outputs."""
        for command, output_file, description in commands:
            cmd_to_run = ["sh", "-c", command] if isinstance(command, str) else command
            result = self.k8s.exec_in_pod(namespace, pod, cmd_to_run)
            if output_file:
                self.write_output(result, output_file, description)
            else:
                self.logger.info(f"{description}: {result[:50]}...")

    def _collect_pod_restart_info(
        self, namespace: str, label_selector: str, output_file: str, description: str
    ) -> None:
        """Collect pod restart information for diagnostics."""
        pods = self.k8s._get_pods_by_label(namespace, label_selector)

        restart_info = []
        for pod in pods.items:
            restart_info.append(f"Pod: {pod.metadata.name}")
            restart_info.append(f"  Started: {pod.status.start_time}")
            for container_status in pod.status.container_statuses or []:
                restart_info.append(
                    f"  Container {container_status.name}: restarts={container_status.restart_count}"
                )

        if restart_info:
            self.write_output("\n".join(restart_info), output_file, description)

    def _ensure_admin_password(self) -> None:
        """Ensure admin password is loaded from secret."""
        if not self.admin_password:
            self.admin_password = self.k8s.get_secret_value(
                HARBOR_NAMESPACE, HARBOR_OIDC_SECRET, HARBOR_ADMIN_PASSWORD_KEY
            )
