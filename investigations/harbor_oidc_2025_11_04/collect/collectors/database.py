"""Database collection for Harbor OIDC investigation."""

import asyncio
from datetime import datetime

from ..config import (
    AUTHENTIK_NAMESPACE,
    AUTHENTIK_POSTGRESQL,
    HARBOR_DATABASE_POD,
    HARBOR_NAMESPACE,
    POSTGRES_USER,
    REGISTRY_DB,
)
from .base import BaseCollector


class DatabaseCollector(BaseCollector):
    """Collector for database information via full dumps."""

    async def collect(self) -> None:
        """Collect ALL database information via full dumps."""
        self.logger.info("Collecting database information via full dumps")

        await asyncio.gather(
            self._dump_database(
                namespace=HARBOR_NAMESPACE,
                pod=HARBOR_DATABASE_POD,
                user=POSTGRES_USER,
                database=REGISTRY_DB,
                host="harbor-database",
                prefix="harbor",
            ),
            self._dump_database(
                namespace=AUTHENTIK_NAMESPACE,
                pod=self.k8s._get_first_pod_by_component(
                    AUTHENTIK_NAMESPACE, "postgresql"
                ),
                user=AUTHENTIK_POSTGRESQL,
                database="authentik",
                host=None,  # Local connection
                prefix="authentik",
            ),
            self._collect_secret_comparison(),
            self._debug_oidc_job_failure(),
            return_exceptions=True,
        )

    async def _debug_oidc_job_failure(self) -> None:
        """Debug the OIDC configuration job failure."""
        self.logger.info("Debugging OIDC configuration job failure")

        debug_result = self.debug_oidc_config_failure()
        self.write_output(
            debug_result, "databases/oidc-config-debug.txt", "OIDC Configuration Debug"
        )

        # Test Harbor secret setting in isolation
        test_result = self.test_harbor_secret_setting()
        self.write_output(
            test_result,
            "databases/harbor-secret-test.txt",
            "Harbor Secret Setting Test",
        )

        # Test Harbor secret decryption
        decryption_result = self.test_harbor_secret_decryption()
        self.write_output(
            decryption_result,
            "databases/harbor-decryption-test.txt",
            "Harbor Secret Decryption Test",
        )

    async def _dump_database(
        self, namespace: str, pod: str, user: str, database: str, host: str, prefix: str
    ) -> None:
        """Create complete database dump with quick config extraction."""
        if not pod:
            self.logger.error(f"❌ No {prefix} PostgreSQL pod found")
            return

        self.logger.info(f"Creating {prefix} database dump")

        # Get PostgreSQL password from secret
        if prefix == "harbor":
            pg_password = self.k8s.get_secret_value(
                "harbor", "harbor-database", "POSTGRES_PASSWORD"
            )
        else:  # authentik
            pg_password = self.k8s.get_secret_value(
                "authentik", "authentik-postgresql", "postgres-password"
            )

        if not pg_password:
            self.logger.error(f"❌ Could not get PostgreSQL password for {prefix}")
            return

        # Execute PostgreSQL commands with consistent authentication
        await asyncio.gather(
            self._exec_postgres_cmd(
                namespace,
                pod,
                pg_password,
                host,
                user,
                database,
                "pg_dump",
                ["--verbose", "--clean", "--if-exists"],
                f"databases/{prefix}-full-dump.sql",
                f"{prefix.title()} Complete Database Dump",
            ),
            self._exec_postgres_cmd(
                namespace,
                pod,
                pg_password,
                host,
                user,
                database,
                "psql",
                ["-c", "\\dt+"],
                f"databases/{prefix}-schema.txt",
                f"{prefix.title()} Database Schema",
            ),
            self._exec_prefix_specific_queries(
                namespace, pod, pg_password, host, user, database, prefix
            ),
            return_exceptions=True,
        )

    async def _exec_postgres_cmd(
        self,
        namespace: str,
        pod: str,
        password: str,
        host: str,
        user: str,
        database: str,
        cmd: str,
        args: list,
        output_file: str,
        description: str,
    ) -> None:
        """Execute a PostgreSQL command with authentication."""
        result = self._exec_psql_query(
            namespace, pod, password, host, user, database, cmd, args
        )
        self.write_output(result, output_file, description)

    def _exec_psql_query(
        self,
        namespace: str,
        pod: str,
        password: str,
        host: str,
        user: str,
        database: str,
        cmd: str,
        args: list,
    ) -> str:
        """Helper to run PostgreSQL queries with authentication - returns raw output."""
        host_part = f"-h {host}" if host else ""
        env_vars = f"PGPASSWORD='{password}'"
        full_cmd = (
            f"{env_vars} {cmd} {host_part} -U {user} -d {database} {' '.join(args)}"
        )
        return self.k8s.exec_in_pod(namespace, pod, ["sh", "-c", full_cmd])

    def exec_harbor_query(self, query: str) -> str:
        """Helper to execute a query on Harbor database."""
        password = self.k8s.get_secret_value(
            "harbor", "harbor-database", "POSTGRES_PASSWORD"
        )
        if not password:
            return "Error: Could not get Harbor PostgreSQL password"
        return self._exec_psql_query(
            "harbor",
            "harbor-database-0",
            password,
            "harbor-database",
            "postgres",
            "registry",
            "psql",
            ["-c", f'"{query}"'],
        )

    def exec_authentik_query(self, query: str) -> str:
        """Helper to execute a query on Authentik database."""
        password = self.k8s.get_secret_value(
            "authentik", "authentik-postgresql", "postgres-password"
        )
        pod = self.k8s._get_first_pod_by_component("authentik", "postgresql")
        if not password or not pod:
            return "Error: Could not get Authentik PostgreSQL credentials"
        return self._exec_psql_query(
            "authentik",
            pod,
            password,
            None,
            "authentik",
            "authentik",
            "psql",
            ["-c", f'"{query}"'],
        )

    def debug_oidc_config_failure(self) -> str:
        """Debug why the oidc-config job failed by testing each step."""
        self.logger.info("Debugging OIDC configuration job failure")

        # Get secrets
        client_secret = self.k8s.get_secret_value(
            "harbor", "harbor-oidc-secret", "OIDC_CLIENT_SECRET"
        )
        admin_password = self.k8s.get_secret_value(
            "harbor", "harbor-oidc-secret", "HARBOR_ADMIN_PASSWORD"
        )

        if not client_secret or not admin_password:
            return "❌ Could not retrieve required secrets"

        # Test Harbor connectivity and configuration steps
        harbor_core_pod = self.k8s._get_first_pod_by_component("harbor", "core")
        if not harbor_core_pod:
            return "❌ Could not find Harbor core pod"

        debug_script = """
set +e  # Don't exit on error, continue debugging
echo "=== Debug OIDC Configuration ==="
echo "HARBOR_CLIENT_SECRET length: ${#HARBOR_CLIENT_SECRET}"
echo "HARBOR_ADMIN_PASSWORD length: ${#HARBOR_ADMIN_PASSWORD}"

echo "Step 1: Testing Harbor connectivity..."
if curl -f -s http://harbor-core:80/api/v2.0/ping >/dev/null 2>&1; then
  echo "✅ Harbor ping successful"
else
  echo "❌ Harbor ping failed"
  echo "Detailed ping test:"
  curl -v http://harbor-core:80/api/v2.0/ping 2>&1 || true
fi

echo "Step 2: Testing deprecated session-based login (EXPECTED TO FAIL)..."
COOKIE_JAR=$(mktemp)
LOGIN_RESPONSE=$(curl -X POST -H "Content-Type: application/x-www-form-urlencoded" \\
  -d "principal=admin&password=$HARBOR_ADMIN_PASSWORD" \\
  -c "$COOKIE_JAR" \\
  -w "%{http_code}" \\
  -o /tmp/login_response.txt \\
  -s \\
  http://harbor-core:80/c/login 2>&1)

echo "Session login HTTP status: $LOGIN_RESPONSE (403 CSRF error expected)"
if [ -f /tmp/login_response.txt ]; then
  echo "Session login response:"
  cat /tmp/login_response.txt
fi

echo "Step 3: Testing WRONG configuration API endpoint (EXPECTED TO FAIL)..."
CONFIG_RESPONSE_WRONG=$(curl -X PUT -H "Content-Type: application/json" \\
  -u admin:$HARBOR_ADMIN_PASSWORD \\
  -d '{
    "auth_mode": "oidc_auth",
    "oidc_name": "Authentik",
    "oidc_endpoint": "https://auth.k3s.agentydragon.com/application/o/harbor/",
    "oidc_client_id": "harbor",
    "oidc_client_secret": "'$client_secret'",
    "oidc_groups_claim": "groups",
    "oidc_admin_group": "harbor-admins",
    "oidc_scope": "openid,profile,email,groups",
    "oidc_user_claim": "preferred_username",
    "oidc_verify_cert": true,
    "oidc_auto_onboard": true
  }' \\
  -w "%{http_code}" \\
  -o /tmp/config_wrong_response.txt \\
  -s \\
  http://harbor-core:80/api/internal/configurations 2>&1)

echo "Wrong endpoint HTTP status: $CONFIG_RESPONSE_WRONG (404 expected)"
if [ -f /tmp/config_wrong_response.txt ]; then
  echo "Wrong endpoint response:"
  head -5 /tmp/config_wrong_response.txt
fi

echo "Step 4: Testing CORRECT configuration API endpoint (SHOULD WORK)..."
CONFIG_RESPONSE_CORRECT=$(curl -X PUT -H "Content-Type: application/json" \\
  -u admin:$HARBOR_ADMIN_PASSWORD \\
  -d '{
    "auth_mode": "oidc_auth",
    "oidc_name": "Authentik",
    "oidc_endpoint": "https://auth.k3s.agentydragon.com/application/o/harbor/",
    "oidc_client_id": "harbor",
    "oidc_client_secret": "'$client_secret'",
    "oidc_groups_claim": "groups",
    "oidc_admin_group": "harbor-admins",
    "oidc_scope": "openid,profile,email,groups",
    "oidc_user_claim": "preferred_username",
    "oidc_verify_cert": true,
    "oidc_auto_onboard": true
  }' \\
  -w "%{http_code}" \\
  -o /tmp/config_correct_response.txt \\
  -s \\
  http://harbor-core:80/api/v2.0/configurations 2>&1)

echo "Correct endpoint HTTP status: $CONFIG_RESPONSE_CORRECT"
if [ -f /tmp/config_correct_response.txt ]; then
  echo "Correct endpoint response:"
  cat /tmp/config_correct_response.txt
fi

echo "Step 5: Detecting common Harbor API configuration issues..."
if [ "$LOGIN_RESPONSE" = "403" ] && grep -q "CSRF" /tmp/login_response.txt 2>/dev/null; then
  echo "🔍 DETECTED: CSRF token error in session login (configuration job using wrong auth method)"
fi

if [ "$CONFIG_RESPONSE_WRONG" = "404" ]; then
  echo "🔍 DETECTED: Wrong API endpoint /api/internal/configurations returns 404 (should use /api/v2.0/configurations)"
fi

if [ "$CONFIG_RESPONSE_CORRECT" = "200" ]; then
  echo "🔍 DETECTED: Harbor API configuration is working correctly with basic auth + /api/v2.0/configurations"
  echo "✅ OIDC Configuration successful - Harbor database should now contain correct client secret"
else
  echo "🔍 DETECTED: Harbor API configuration still failing - check credentials or Harbor version compatibility"
  echo "❌ Configuration API test failed with status $CONFIG_RESPONSE_CORRECT"
fi

rm -f "$COOKIE_JAR" /tmp/login_response.txt /tmp/config_wrong_response.txt /tmp/config_correct_response.txt
echo "=== Debug completed ==="
"""

        # Execute debug script in Harbor core pod
        return self.k8s.exec_in_pod(
            "harbor",
            harbor_core_pod,
            [
                "sh",
                "-c",
                f"HARBOR_CLIENT_SECRET='{client_secret}' HARBOR_ADMIN_PASSWORD='{admin_password}' {debug_script}",
            ],
        )

    async def _exec_prefix_specific_queries(
        self,
        namespace: str,
        pod: str,
        password: str,
        host: str,
        user: str,
        database: str,
        prefix: str,
    ) -> None:
        """Execute database-specific configuration queries."""
        if prefix == "harbor":
            await self._exec_postgres_cmd(
                namespace,
                pod,
                password,
                host,
                user,
                database,
                "psql",
                [
                    "-c",
                    "\"SELECT k, v FROM properties WHERE k LIKE '%oidc%' OR k = 'auth_mode' ORDER BY k;\"",
                ],
                f"databases/{prefix}-oidc-config.txt",
                "Harbor OIDC Configuration",
            )
        elif prefix == "authentik":
            await self._exec_postgres_cmd(
                namespace,
                pod,
                password,
                host,
                user,
                database,
                "psql",
                [
                    "-c",
                    "\"SELECT name, client_id, client_secret, redirect_uris FROM authentik_providers_oauth2_oauth2provider WHERE client_id = 'harbor';\"",
                ],
                f"databases/{prefix}-harbor-client.txt",
                "Authentik Harbor OAuth2 Client Configuration",
            )

    async def _collect_secret_comparison(self) -> None:
        """Compare client secrets between Harbor, Authentik, and Kubernetes secrets."""
        self.logger.info("Collecting secret comparison data")

        try:
            # Get Harbor database password
            harbor_pg_password = self.k8s.get_secret_value(
                "harbor", "harbor-database", "POSTGRES_PASSWORD"
            )
            if not harbor_pg_password:
                self.logger.error("❌ Could not get Harbor PostgreSQL password")
                return

            # Get Harbor stored secret (encrypted) from database using deduplicated method
            env_vars = f"PGPASSWORD='{harbor_pg_password}'"
            harbor_secret_cmd = f"{env_vars} psql -h harbor-database -U postgres -d registry -c \"SELECT k, v FROM properties WHERE k = 'oidc_client_secret';\""
            harbor_secret_result = self.k8s.exec_in_pod(
                "harbor", "harbor-database-0", ["sh", "-c", harbor_secret_cmd]
            )

            # Get Kubernetes secrets using K8s SDK
            harbor_k8s_secret = self.k8s.get_secret_value(
                "harbor", "harbor-oidc-secret", "OIDC_CLIENT_SECRET"
            )
            authentik_k8s_secret = self.k8s.get_secret_value(
                "authentik", "authentik-harbor-oauth", "client-secret"
            )

            # Get Harbor OIDC config job status using K8s SDK
            try:
                job_status = self.k8s.batch_v1.read_namespaced_job_status(
                    "harbor-oidc-config", "harbor"
                )
                job_info = f"""
Job Status: {job_status.status}
Conditions: {job_status.status.conditions if job_status.status.conditions else "None"}
Start Time: {job_status.status.start_time}
Completion Time: {job_status.status.completion_time}
Succeeded: {job_status.status.succeeded}
Failed: {job_status.status.failed}
"""
            except Exception as e:
                job_info = f"Job status error: {e!s}"

            # Compare secrets
            secrets_match = (
                harbor_k8s_secret == authentik_k8s_secret
                if harbor_k8s_secret and authentik_k8s_secret
                else False
            )

            # Compile secret comparison report
            secret_report = f"""# Harbor OIDC Secret Comparison Report
# Generated: {datetime.now()}

## Harbor Database Secret (encrypted):
{harbor_secret_result}

## Harbor K8s Secret (plaintext):
{harbor_k8s_secret or "Error retrieving secret"}

## Authentik K8s Secret (plaintext):  
{authentik_k8s_secret or "Error retrieving secret"}

## Harbor OIDC Config Job Status:
{job_info}

## Secret Analysis:
- Harbor/Authentik secrets match: {secrets_match}
- Harbor secret length: {len(harbor_k8s_secret) if harbor_k8s_secret else "N/A"}
- Authentik secret length: {len(authentik_k8s_secret) if authentik_k8s_secret else "N/A"}
- Both secrets present: {bool(harbor_k8s_secret and authentik_k8s_secret)}

## Root Cause Analysis:
The OAuth2 'invalid_client' error indicates Harbor's database still contains 
an outdated encrypted client secret that doesn't match the current plaintext 
secret stored in Kubernetes. The harbor-oidc-config job should have updated 
Harbor's database via API, but appears to have failed or not run.

## Fix Required:
1. Verify harbor-oidc-config job completed successfully  
2. If not, re-run the job or manually update Harbor via API:
   curl -X PUT -u admin:PASSWORD \\
     -H "Content-Type: application/json" \\
     -d '{{"oidc_client_secret": "{harbor_k8s_secret or "SECRET"}"}}' \\
     http://harbor-core:8080/api/v2.0/configurations
"""

            self.write_output(
                secret_report,
                "databases/secret-comparison-report.txt",
                "Harbor OIDC Secret Comparison Report",
            )

        except Exception as e:
            error_report = f"# Secret Comparison Failed\n# Error: {e!s}\n# Time: {datetime.now()}\n"
            self.write_output(
                error_report,
                "databases/secret-comparison-error.txt",
                "Secret Comparison Error",
            )

    def test_harbor_secret_setting(self) -> str:
        """Test Harbor secret setting and retrieval in isolation with known test values."""
        self.logger.info("Testing Harbor secret setting in isolation")

        admin_password = self.k8s.get_secret_value(
            "harbor", "harbor-oidc-secret", "HARBOR_ADMIN_PASSWORD"
        )

        if not admin_password:
            return "❌ Could not retrieve Harbor admin password for testing"

        harbor_core_pod = self.k8s._get_first_pod_by_component("harbor", "core")
        if not harbor_core_pod:
            return "❌ Could not find Harbor core pod"

        # Define test secrets to try
        test_secrets = ["test_secret_123", "another_test_456", "final_test_789"]

        results = []
        results.append("=== Harbor Secret Setting Isolation Test ===")
        results.append(f"Generated at: {datetime.now()}")
        results.append("")

        for i, test_secret in enumerate(test_secrets, 1):
            results.append(f"--- Test {i}: Setting secret to '{test_secret}' ---")

            # Set the test secret via Harbor API
            set_result = self._set_harbor_test_secret(
                harbor_core_pod, admin_password, test_secret
            )
            results.append(f"API Set Result: {set_result}")

            # Read back the encrypted secret from database
            db_secret = self._get_harbor_db_secret()
            results.append(f"DB Encrypted Secret: {db_secret}")

            # Try to verify via API (should match what we set)
            api_verification = self._verify_harbor_secret_via_api(
                harbor_core_pod, admin_password
            )
            results.append(f"API Verification: {api_verification}")
            results.append("")

        return "\n".join(results)

    def _set_harbor_test_secret(
        self, pod: str, admin_password: str, test_secret: str
    ) -> str:
        """Set a test secret via Harbor API."""
        script = f"""
curl -X PUT \\
  -H "Content-Type: application/json" \\
  -u admin:{admin_password} \\
  -d '{{"oidc_client_secret": "{test_secret}"}}' \\
  -w "HTTP_%{{http_code}}" \\
  -o /tmp/set_response.txt \\
  -s \\
  http://harbor-core:80/api/v2.0/configurations 2>&1

echo -n "Status: "
cat /tmp/set_response.txt | tail -c 8
echo ""
echo -n "Response: "
cat /tmp/set_response.txt | head -c -8
"""
        return self.k8s.exec_in_pod("harbor", pod, ["sh", "-c", script])

    def _get_harbor_db_secret(self) -> str:
        """Get the current encrypted secret from Harbor database."""
        return self.exec_harbor_query(
            "SELECT v FROM properties WHERE k = 'oidc_client_secret'"
        )

    def _verify_harbor_secret_via_api(self, pod: str, admin_password: str) -> str:
        """Get current OIDC configuration via API to verify secret was set."""
        script = f"""
curl -s -u admin:{admin_password} \\
  http://harbor-core:80/api/v2.0/configurations \\
  | python3 -c "
import sys, json
try:
    config = json.load(sys.stdin)
    # Harbor API doesn't return the secret for security, just verify config exists
    if 'oidc_client_secret' in config:
        print('✅ OIDC client secret field exists in API response')
    else:
        print('❌ OIDC client secret field missing from API response')
    
    auth_mode = config.get('auth_mode', {{}}).get('value', 'unknown')
    print('Auth mode:', auth_mode)
except Exception as e:
    print('❌ JSON parse error:', str(e))
"
"""
        return self.k8s.exec_in_pod("harbor", pod, ["sh", "-c", script])

    def test_harbor_secret_decryption(self) -> str:
        """Test the actual Harbor configuration script with known values."""
        self.logger.info("Testing actual Harbor configuration script")

        admin_password = self.k8s.get_secret_value(
            "harbor", "harbor-oidc-secret", "HARBOR_ADMIN_PASSWORD"
        )
        expected_secret = self.k8s.get_secret_value(
            "harbor", "harbor-oidc-secret", "OIDC_CLIENT_SECRET"
        )

        if not admin_password or not expected_secret:
            return "❌ Could not retrieve Harbor secrets for testing"

        harbor_core_pod = self.k8s._get_first_pod_by_component("harbor", "core")
        if not harbor_core_pod:
            return "❌ Could not find Harbor core pod"

        results = []
        results.append("=== Harbor Configuration Script Test ===")
        results.append(f"Generated at: {datetime.now()}")
        results.append(f"Testing with K8s secret: {expected_secret}")
        results.append("")

        # Step 1: Get current state
        current_db_secret = self._get_harbor_db_secret()
        results.append(f"Before script - DB encrypted: {current_db_secret.strip()}")

        # Step 2: Run the ACTUAL Harbor configuration script with test values
        results.append("\n--- Running actual Harbor config script ---")
        script_result = self._run_actual_harbor_config_script(
            harbor_core_pod, admin_password, "TEST_SECRET_12345"
        )
        results.append(f"Script execution result:\n{script_result}")

        # Step 3: Check what got stored
        new_db_secret = self._get_harbor_db_secret()
        results.append(f"\nAfter script - DB encrypted: {new_db_secret.strip()}")

        # Step 4: Now test with the real K8s secret
        results.append("\n--- Running with real K8s secret ---")
        real_script_result = self._run_actual_harbor_config_script(
            harbor_core_pod, admin_password, expected_secret
        )
        results.append(f"Real secret script result:\n{real_script_result}")

        final_db_secret = self._get_harbor_db_secret()
        results.append(f"\nFinal DB encrypted: {final_db_secret.strip()}")

        return "\n".join(results)

    def _run_actual_harbor_config_script(
        self, pod: str, admin_password: str, client_secret: str
    ) -> str:
        """Run the actual Harbor configuration script from the Helm chart."""
        # This is the exact script from configure-harbor.sh
        script = f'''
echo "==========================================="
echo "STEP 4: Configuring Harbor OIDC settings"
echo "==========================================="

echo "Updating OIDC configuration via API..."
if curl -X PUT \\
  -H "Content-Type: application/json" \\
  -u admin:{admin_password} \\
  -d '{{
    "auth_mode": "oidc_auth",
    "oidc_name": "Authentik",
    "oidc_endpoint": "https://auth.k3s.agentydragon.com/application/o/harbor/",
    "oidc_client_id": "harbor",
    "oidc_client_secret": "{client_secret}",
    "oidc_groups_claim": "groups",
    "oidc_admin_group": "harbor-admins",
    "oidc_scope": "openid,profile,email,groups",
    "oidc_user_claim": "preferred_username",
    "oidc_verify_cert": true,
    "oidc_auto_onboard": true
  }}' \\
  --fail-with-body \\
  http://harbor-core:80/api/v2.0/configurations; then
  echo "✅ OIDC configuration updated successfully"
else
  echo "❌ Failed to update OIDC configuration"
  exit 1
fi
'''
        return self.k8s.exec_in_pod("harbor", pod, ["sh", "-c", script])
