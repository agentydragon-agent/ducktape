"""Secret comparison collector for Harbor OIDC investigation."""

import asyncio
import json
from typing import Any, Dict, Optional

from .base import BaseCollector


class SecretsCollector(BaseCollector):
    """Collects and compares secrets across systems."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_k8s_secret(self) -> Optional[str]:
        """Get the OIDC client secret from Kubernetes."""
        try:
            result = await self.k8s.run_kubectl(
                "get secret harbor-oidc-secret -n harbor "
                "-o jsonpath='{.data.OIDC_CLIENT_SECRET}'"
            )
            if result and result.get("exit_code") == 0:
                import base64

                encoded = result.get("stdout", "")
                return base64.b64decode(encoded).decode().strip()
            return (
                result.get("stdout", "").strip()
                if result.get("exit_code") == 0
                else None
            )
        except Exception as e:
            self.logger.error(f"Failed to get K8s secret: {e}")
            return None

    async def get_authentik_secret(self) -> Optional[str]:
        """Get the client secret from Authentik."""
        try:
            cmd = (
                "kubectl exec -n authentik deployment/authentik-server -- "
                'ak shell -c "from authentik.providers.oauth2.models import OAuth2Provider; '
                "p = OAuth2Provider.objects.filter(client_id='harbor').first(); "
                "print(p.client_secret if p else 'NOT_FOUND')\""
            )
            result = await self.k8s.run_kubectl(
                f"exec -n authentik deployment/authentik-server -- {cmd.split('kubectl exec -n authentik deployment/authentik-server -- ')[1]}"
            )
            if result.get("exit_code") == 0:
                # Parse output, skipping log lines
                for line in result.get("stdout", "").strip().split("\n"):
                    if not line.startswith("{") and line != "NOT_FOUND":
                        return line.strip()
            return None
        except Exception as e:
            self.logger.error(f"Failed to get Authentik secret: {e}")
            return None

    async def get_harbor_db_secret(self) -> Optional[str]:
        """Get the encrypted secret from Harbor database."""
        try:
            result = await self.k8s.run_kubectl(
                "exec -n harbor harbor-database-0 -- "
                "psql -U postgres -d registry -t -c "
                "\"SELECT v FROM properties WHERE k = 'oidc_client_secret';\" | xargs"
            )
            if result.get("exit_code") == 0:
                # Extract just the encrypted value
                output = result.get("stdout", "").strip()
                for line in output.split("\n"):
                    if line.startswith("<enc-v1>"):
                        return line.strip()
            return None
        except Exception as e:
            self.logger.error(f"Failed to get Harbor DB secret: {e}")
            return None

    async def get_vault_secret(self) -> Optional[str]:
        """Get the secret from Vault (if accessible)."""
        try:
            # Try to get from vault via kubectl exec on a pod with vault access
            cmd = (
                "kubectl exec -n vault vault-0 -- "
                "vault kv get -format=json kv/harbor/oidc 2>/dev/null | "
                "jq -r '.data.data.client_secret'"
            )
            result = await self.k8s.run_kubectl(
                f"exec -n vault vault-0 -- {cmd.split('kubectl exec -n vault vault-0 -- ')[1]}"
            )
            if (
                result.get("exit_code") == 0
                and result.get("stdout", "").strip() != "null"
            ):
                return result.get("stdout", "").strip()
        except Exception:
            pass
        return None

    async def check_harbor_api_config(self) -> Dict[str, Any]:
        """Get OIDC configuration from Harbor API."""
        try:
            # First get admin password
            pwd_result = await self.k8s.run_kubectl(
                "get secret harbor-oidc-secret -n harbor "
                "-o jsonpath='{.data.HARBOR_ADMIN_PASSWORD}'"
            )
            if pwd_result and pwd_result.get("exit_code") == 0:
                import base64

                encoded = pwd_result.get("stdout", "")
                admin_pwd = base64.b64decode(encoded).decode().strip()
            else:
                admin_pwd = ""
            admin_pwd = (
                pwd_result.get("stdout", "").strip()
                if pwd_result.get("exit_code") == 0
                else ""
            )

            # Get configuration via API
            cmd = (
                f"kubectl exec -n harbor deployment/harbor-core -- "
                f"curl -s -u admin:{admin_pwd} http://localhost:8080/api/v2.0/configurations"
            )
            result = await self.k8s.run_kubectl(
                f"exec -n harbor deployment/harbor-core -- curl -s -u admin:{admin_pwd} http://localhost:8080/api/v2.0/configurations"
            )
            if result.get("exit_code") == 0:
                config = json.loads(result.get("stdout", ""))
                oidc_config = {}
                for key in [
                    "auth_mode",
                    "oidc_name",
                    "oidc_endpoint",
                    "oidc_client_id",
                    "oidc_groups_claim",
                    "oidc_admin_group",
                    "oidc_scope",
                    "oidc_user_claim",
                    "oidc_verify_cert",
                    "oidc_auto_onboard",
                ]:
                    if key in config:
                        oidc_config[key] = config[key].get("value")
                return oidc_config
        except Exception as e:
            self.logger.error(f"Failed to get Harbor API config: {e}")
        return {}

    async def collect(self) -> None:
        """Collect and compare all secrets."""
        self.logger.info("Collecting and comparing secrets")

        # Collect all secrets in parallel
        results = await asyncio.gather(
            self.get_k8s_secret(),
            self.get_authentik_secret(),
            self.get_harbor_db_secret(),
            self.get_vault_secret(),
            self.check_harbor_api_config(),
            return_exceptions=True,
        )

        k8s_secret, authentik_secret, harbor_db_secret, vault_secret, harbor_config = (
            results
        )

        # Process exceptions
        for i, name in enumerate(
            ["K8s", "Authentik", "Harbor DB", "Vault", "Harbor API"]
        ):
            if isinstance(results[i], Exception):
                self.logger.error(f"Failed to get {name} secret: {results[i]}")
                results[i] = None

        # Build comparison report
        report = {
            "secrets": {
                "kubernetes": {
                    "value": k8s_secret,
                    "source": "harbor-oidc-secret in harbor namespace",
                },
                "authentik": {
                    "value": authentik_secret,
                    "source": "OAuth2Provider with client_id=harbor",
                },
                "harbor_database": {
                    "value": harbor_db_secret,
                    "encrypted": True,
                    "source": "properties table, key=oidc_client_secret",
                },
                "vault": {"value": vault_secret, "source": "kv/harbor/oidc"},
            },
            "comparison": {
                "k8s_matches_authentik": k8s_secret == authentik_secret
                if k8s_secret and authentik_secret
                else None,
                "k8s_matches_vault": k8s_secret == vault_secret
                if k8s_secret and vault_secret
                else None,
                "authentik_matches_vault": authentik_secret == vault_secret
                if authentik_secret and vault_secret
                else None,
                "harbor_db_is_encrypted": harbor_db_secret.startswith("<enc-v1>")
                if harbor_db_secret
                else False,
            },
            "harbor_api_config": harbor_config,
            "issues": [],
        }

        # Identify issues
        if k8s_secret and authentik_secret and k8s_secret != authentik_secret:
            report["issues"].append(
                "CRITICAL: K8s secret does not match Authentik secret"
            )

        if vault_secret and k8s_secret and vault_secret != k8s_secret:
            report["issues"].append(
                "WARNING: Vault secret does not match K8s secret (ESO sync issue?)"
            )

        if harbor_db_secret and not harbor_db_secret.startswith("<enc-v1>"):
            report["issues"].append("WARNING: Harbor DB secret is not encrypted")

        if not harbor_db_secret:
            report["issues"].append("CRITICAL: Harbor DB secret is missing")

        if harbor_config.get("auth_mode", {}) != "oidc_auth":
            report["issues"].append(
                f"CRITICAL: Harbor auth mode is '{harbor_config.get('auth_mode')}', expected 'oidc_auth'"
            )

        # Save report
        self.write_output(
            json.dumps(report, indent=2),
            "secrets-comparison.json",
            "Secret comparison report",
        )

        # Generate markdown report
        md_report = self._generate_markdown_report(report)
        self.write_output(
            md_report, "secrets-comparison.md", "Secret comparison markdown report"
        )

        self.logger.info(
            f"Secret comparison complete. Found {len(report['issues'])} issues"
        )
        for issue in report["issues"]:
            self.logger.warning(issue)

    def _generate_markdown_report(self, report: Dict[str, Any]) -> str:
        """Generate a markdown report from the comparison data."""
        lines = ["# Secret Comparison Report", ""]

        # Issues section
        if report["issues"]:
            lines.append("## ⚠️ Issues Found")
            for issue in report["issues"]:
                lines.append(f"- {issue}")
            lines.append("")
        else:
            lines.append("## ✅ No Issues Found")
            lines.append("")

        # Secret values
        lines.append("## Secret Values")
        lines.append("| System | Value | Source |")
        lines.append("|--------|-------|--------|")

        for system, data in report["secrets"].items():
            value = data["value"] if data["value"] else "NOT FOUND"
            if system == "harbor_database" and data.get("encrypted"):
                value = f"{value[:20]}... (encrypted)"
            elif value and value != "NOT FOUND" and len(value) > 20:
                value = f"{value[:10]}...{value[-10:]}"
            lines.append(f"| {system} | `{value}` | {data['source']} |")

        lines.append("")

        # Comparison matrix
        lines.append("## Comparison Matrix")
        for key, value in report["comparison"].items():
            if value is not None:
                status = "✅" if value else "❌"
                lines.append(f"- {key.replace('_', ' ').title()}: {status}")

        lines.append("")

        # Harbor configuration
        if report["harbor_api_config"]:
            lines.append("## Harbor OIDC Configuration")
            lines.append("| Setting | Value |")
            lines.append("|---------|-------|")
            for key, value in report["harbor_api_config"].items():
                lines.append(f"| {key} | `{value}` |")

        return "\n".join(lines)
