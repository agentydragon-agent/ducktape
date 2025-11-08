"""API endpoint testing for Harbor OIDC investigation."""

from typing import Optional

import aiohttp

from ..config import (
    AUTHENTIK_BASE_URL,
    HARBOR_ADMIN_PASSWORD_KEY,
    HARBOR_BASE_URL,
    HARBOR_CORE_POD,
    HARBOR_NAMESPACE,
    HARBOR_OIDC_SECRET,
)
from .base import BaseCollector


class APICollector(BaseCollector):
    """Collector for API endpoint tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_password = None

    async def collect(self) -> None:
        """Test API endpoints."""
        self.logger.info("🔗 TESTING API ENDPOINTS...")

        self._ensure_admin_password()

        # Use aiohttp for external API tests
        async with aiohttp.ClientSession() as session:
            endpoints = [
                (
                    f"{HARBOR_BASE_URL}/api/v2.0/ping",
                    None,
                    "harbor-ping.txt",
                ),
                (
                    f"{HARBOR_BASE_URL}/api/v2.0/systeminfo",
                    None,
                    "harbor-systeminfo.txt",
                ),
                (
                    f"{HARBOR_BASE_URL}/c/oidc/login",
                    None,
                    "harbor-oidc-login.txt",
                ),
                (
                    f"{AUTHENTIK_BASE_URL}/application/o/harbor/.well-known/openid-configuration",
                    None,
                    "authentik-discovery.txt",
                ),
            ]

            for url, auth, output_file in endpoints:
                await self._test_endpoint(
                    session, url, auth, f"api_tests/{output_file}"
                )

        # Internal tests via pod exec
        internal_tests = [
            ("curl -I http://localhost:8080/c/oidc/login", "harbor-internal-oidc.txt"),
            (
                "curl http://localhost:8080/api/v2.0/systeminfo | jq .auth_mode",
                "harbor-internal-auth.txt",
            ),
        ]

        self._run_pod_commands(
            HARBOR_NAMESPACE,
            HARBOR_CORE_POD,
            [
                (cmd, f"api_tests/{output_file}", f"Internal test: {cmd}")
                for cmd, output_file in internal_tests
            ],
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

    async def _test_endpoint(
        self,
        session: aiohttp.ClientSession,
        url: str,
        auth: Optional[tuple[str, str]],
        output_file: str,
    ) -> None:
        """Test an HTTP endpoint."""
        try:
            kwargs = {"ssl": False}  # Skip SSL verification for internal certs
            if auth:
                kwargs["auth"] = aiohttp.BasicAuth(auth[0], auth[1])

            async with session.get(url, **kwargs) as resp:
                content = await resp.text()
                headers = "\n".join([f"{k}: {v}" for k, v in resp.headers.items()])
                output = (
                    f"Status: {resp.status}\n\nHeaders:\n{headers}\n\nBody:\n{content}"
                )
                self.write_output(output, output_file, f"API test: {url}")
        except Exception as e:
            self.write_output(str(e), output_file, f"API test failed: {url}")

    def _ensure_admin_password(self) -> None:
        """Ensure admin password is loaded from secret."""
        if not self.admin_password:
            self.admin_password = self.k8s.get_secret_value(
                HARBOR_NAMESPACE, HARBOR_OIDC_SECRET, HARBOR_ADMIN_PASSWORD_KEY
            )
