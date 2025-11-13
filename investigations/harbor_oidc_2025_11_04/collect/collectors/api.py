"""API endpoint testing for Harbor OIDC investigation."""

from typing import Optional

import aiohttp

from ..config import (
    AUTHENTIK_BASE_URL,
    HARBOR_ADMIN_PASSWORD_KEY,
    HARBOR_BASE_URL,
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
        self.logger.info("Testing API endpoints")

        self._ensure_admin_password()

        # Use aiohttp for external API tests
        async with aiohttp.ClientSession() as session:
            endpoints = [
                (f"{HARBOR_BASE_URL}/api/v2.0/ping", None, "harbor-ping.txt", "GET"),
                (
                    f"{HARBOR_BASE_URL}/api/v2.0/systeminfo",
                    None,
                    "harbor-systeminfo.txt",
                    "GET",
                ),
                (
                    f"{HARBOR_BASE_URL}/c/oidc/login?redirect_url=/harbor/projects",
                    None,
                    "harbor-oidc-login.txt",
                    "GET",
                ),
                (
                    f"{HARBOR_BASE_URL}/c/oidc/login?redirect_url=/harbor/projects",
                    None,
                    "harbor-oidc-login-head.txt",
                    "HEAD",
                ),
                (
                    f"{AUTHENTIK_BASE_URL}/application/o/harbor/.well-known/openid-configuration",
                    None,
                    "authentik-discovery.txt",
                    "GET",
                ),
            ]

            for url, auth, output_file, method in endpoints:
                await self._test_endpoint(
                    session, url, auth, f"api_tests/{output_file}", method
                )

        # Internal tests via pod exec - enhanced for OIDC debugging with full HTTP chains
        internal_tests = [
            (
                "curl -I http://localhost:8080/c/oidc/login",
                "harbor-internal-oidc-head.txt",
            ),
            (
                "curl -s http://localhost:8080/c/oidc/login?redirect_url=/harbor/projects",
                "harbor-internal-oidc-get.txt",
            ),
            (
                "curl http://localhost:8080/api/v2.0/systeminfo | jq .auth_mode",
                "harbor-internal-auth.txt",
            ),
            # Test both methods to understand the HEAD vs GET discrepancy
            (
                "curl -X HEAD -I http://localhost:8080/c/oidc/login 2>&1",
                "harbor-oidc-head-method.txt",
            ),
            (
                "curl -X GET -s http://localhost:8080/c/oidc/login 2>&1",
                "harbor-oidc-get-method.txt",
            ),
            # Check route registration and Harbor version
            (
                "curl -s http://localhost:8080/api/v2.0/systeminfo | jq '.harbor_version, .auth_mode, .oidc_provider_name'",
                "harbor-version-auth-info.txt",
            ),
            # Full HTTP chain capture for OIDC flow
            (
                "curl -v -L -c /tmp/harbor_cookies.txt http://localhost:8080/c/oidc/login?redirect_url=/harbor/projects 2>&1",
                "harbor-oidc-full-chain.txt",
            ),
            (
                "curl -v -b /tmp/harbor_cookies.txt http://localhost:8080/c/oidc/callback?error=access_denied 2>&1",
                "harbor-oidc-callback-test.txt",
            ),
            # Session storage and route testing
            (
                "curl -v -X GET http://localhost:8080/c/oidc/login?redirect_url=/test 2>&1 | grep -E '(HTTP|Location|Set-Cookie)'",
                "harbor-oidc-session-headers.txt",
            ),
            # Test Harbor OIDC configuration endpoints
            (
                "curl -s http://localhost:8080/api/v2.0/systeminfo | jq '.oidc_provider_name, .oidc_scope, .oidc_client_id'",
                "harbor-oidc-config-api.txt",
            ),
            # Harbor-to-Authentik connectivity tests (critical for OAuth2 token exchange)
            (
                "curl -v -w 'DNS_TIME: %{time_namelookup}, CONNECT_TIME: %{time_connect}, TOTAL_TIME: %{time_total}' https://auth.k3s.agentydragon.com/.well-known/openid-configuration 2>&1",
                "harbor-to-authentik-discovery.txt",
            ),
            (
                "curl -v -w 'DNS_TIME: %{time_namelookup}, CONNECT_TIME: %{time_connect}, TOTAL_TIME: %{time_total}' https://auth.k3s.agentydragon.com/application/o/harbor/.well-known/openid-configuration 2>&1",
                "harbor-to-authentik-harbor-discovery.txt",
            ),
            (
                "curl -v -X POST https://auth.k3s.agentydragon.com/application/o/token/ -d 'grant_type=authorization_code&client_id=harbor&code=test' 2>&1",
                "harbor-to-authentik-token-endpoint.txt",
            ),
            ("nslookup auth.k3s.agentydragon.com", "harbor-dns-resolution.txt"),
            ("ping -c 3 auth.k3s.agentydragon.com", "harbor-ping-authentik.txt"),
            # SSL Certificate validation and details
            (
                "openssl s_client -connect auth.k3s.agentydragon.com:443 -servername auth.k3s.agentydragon.com </dev/null 2>&1 | openssl x509 -noout -text",
                "harbor-ssl-cert-details.txt",
            ),
            (
                "openssl s_client -connect auth.k3s.agentydragon.com:443 -servername auth.k3s.agentydragon.com </dev/null 2>&1 | openssl x509 -noout -dates -subject -issuer",
                "harbor-ssl-cert-summary.txt",
            ),
            (
                "echo | openssl s_client -connect auth.k3s.agentydragon.com:443 -servername auth.k3s.agentydragon.com -verify_return_error 2>&1",
                "harbor-ssl-cert-verification.txt",
            ),
            # Test with different cert validation modes
            (
                "curl -v --cacert /etc/ssl/certs/ca-certificates.crt https://auth.k3s.agentydragon.com/application/o/harbor/.well-known/openid-configuration 2>&1",
                "harbor-curl-with-ca-certs.txt",
            ),
            (
                "curl -v -k https://auth.k3s.agentydragon.com/application/o/harbor/.well-known/openid-configuration 2>&1",
                "harbor-curl-insecure.txt",
            ),
            # Check what CA certificates Harbor pod has access to
            ("ls -la /etc/ssl/certs/ | head -20", "harbor-ca-certs-available.txt"),
            ("cat /etc/os-release", "harbor-os-version.txt"),
            # Harbor client secret investigation
            (
                "echo 'SELECT k, v FROM properties WHERE k = \"oidc_client_secret\";' | psql -h harbor-database -U postgres -d registry",
                "harbor-client-secret-raw.txt",
            ),
            # Check for k3s/cluster CA certificates specifically
            (
                "find /var/lib/rancher -name '*.crt' -o -name '*.pem' 2>/dev/null | head -10",
                "harbor-k3s-ca-search.txt",
            ),
            (
                "find /etc -name '*k3s*' -o -name '*cluster*' -name '*.crt' 2>/dev/null",
                "harbor-cluster-certs.txt",
            ),
            ("env | grep -i cert", "harbor-cert-env-vars.txt"),
            (
                "cat /etc/ssl/certs/ca-certificates.crt | grep -A5 -B5 k3s",
                "harbor-ca-bundle-k3s-check.txt",
            ),
            # Check if Harbor has any custom cert mounts
            ("mount | grep cert", "harbor-cert-mounts.txt"),
            (
                "ls -la /harbor_cust_cert/ 2>/dev/null || echo 'No custom cert dir'",
                "harbor-custom-cert-dir.txt",
            ),
            (
                "cat /etc/harbor/ssl/* 2>/dev/null | head -50 || echo 'No Harbor SSL config'",
                "harbor-ssl-config.txt",
            ),
            # Test specific k3s CA trust
            (
                "openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt <(echo | openssl s_client -connect auth.k3s.agentydragon.com:443 -servername auth.k3s.agentydragon.com 2>/dev/null | openssl x509) 2>&1",
                "harbor-verify-against-ca-bundle.txt",
            ),
        ]

        # Get harbor-core pod dynamically
        core_pod = self.k8s._get_first_pod_by_component(HARBOR_NAMESPACE, "core")
        if core_pod:
            self._run_pod_commands(
                HARBOR_NAMESPACE,
                core_pod,
                [
                    (cmd, f"api_tests/{output_file}", f"Internal test: {cmd}")
                    for cmd, output_file in internal_tests
                ],
            )
        else:
            self.logger.error("❌ No Harbor core pod found for internal API tests")

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
        method: str = "GET",
    ) -> None:
        """Test an HTTP endpoint with specified method."""
        try:
            kwargs = {"ssl": False}  # Skip SSL verification for internal certs
            if auth:
                kwargs["auth"] = aiohttp.BasicAuth(auth[0], auth[1])

            # Choose the right method
            if method.upper() == "HEAD":
                async with session.head(url, **kwargs) as resp:
                    content = ""  # HEAD responses don't have body
                    headers = "\n".join([f"{k}: {v}" for k, v in resp.headers.items()])
                    output = f"Method: {method}\nStatus: {resp.status}\n\nHeaders:\n{headers}"
            else:  # Default to GET
                async with session.get(url, **kwargs) as resp:
                    content = await resp.text()
                    headers = "\n".join([f"{k}: {v}" for k, v in resp.headers.items()])
                    output = f"Method: {method}\nStatus: {resp.status}\n\nHeaders:\n{headers}\n\nBody:\n{content}"

            self.write_output(output, output_file, f"API test ({method}): {url}")
        except Exception as e:
            self.write_output(str(e), output_file, f"API test failed ({method}): {url}")

    def _ensure_admin_password(self) -> None:
        """Ensure admin password is loaded from secret."""
        if not self.admin_password:
            self.admin_password = self.k8s.get_secret_value(
                HARBOR_NAMESPACE, HARBOR_OIDC_SECRET, HARBOR_ADMIN_PASSWORD_KEY
            )
