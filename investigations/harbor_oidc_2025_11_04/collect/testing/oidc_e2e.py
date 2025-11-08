"""OIDC E2E testing for Harbor."""

from datetime import datetime
import re

from ..config import (
    AUTHENTIK_NAMESPACE,
    HARBOR_CORE_POD,
    HARBOR_DATABASE_POD,
    HARBOR_NAMESPACE,
    OIDC_LOGIN_CURL_CMD,
    POSTGRES_USER,
    REGISTRY_DB,
)
from .test_users import TestUserManager


class OIDCTester:
    """OIDC end-to-end testing."""

    def __init__(self, k8s_client, file_writer, logger):
        self.k8s = k8s_client
        self.writer = file_writer
        self.logger = logger
        self.test_user_manager = TestUserManager(k8s_client, logger)

    async def test_oidc_e2e_flow(self) -> None:
        """Test complete OIDC login flow end-to-end."""
        self.logger.info("🔐 TESTING E2E OIDC FLOW...")

        test_results = []
        test_username = f"test-oidc-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        test_password = "TestPassword123!"
        test_email = f"{test_username}@test.local"

        # Use context manager to ensure cleanup
        try:
            with self.test_user_manager.authentik_test_user(
                test_username, test_password, test_email
            ) as user_info:
                if "error" in user_info:
                    test_results.append(f"User Creation Failed: {user_info['error']}")
                    self.logger.error(
                        f"❌ Could not create test user: {user_info['error']}"
                    )
                    # Can't proceed without a test user
                else:
                    test_results.append(
                        f"User Creation: {user_info['creation_result']}"
                    )

                    # Step 2: Test OIDC login flow with curl
                    self.logger.info("Testing OIDC login flow...")

                    # Get OIDC login URL and extract state
                    login_test = self.k8s.exec_in_pod(
                        HARBOR_NAMESPACE,
                        HARBOR_CORE_POD,
                        OIDC_LOGIN_CURL_CMD,
                    )
                    test_results.append(f"OIDC Login Response:\n{login_test}")

                    # Parse redirect URL to get authorization endpoint
                    location_match = re.search(r"Location: (.+)", login_test)
                    if location_match:
                        auth_url = location_match.group(1).strip()
                        test_results.append(f"Authorization URL: {auth_url}")

                        # Extract state parameter for later use
                        state_match = re.search(r"state=([^&]+)", auth_url)
                        if state_match:
                            state = state_match.group(1)
                            test_results.append(f"State parameter: {state}")

                    # Step 3: Check if user can authenticate (simulate flow)
                    # Note: Full browser automation would require Selenium/Playwright
                    # For now, we verify the endpoints are working

                    # Test callback endpoint exists
                    callback_test = self.k8s.exec_in_pod(
                        HARBOR_NAMESPACE,
                        HARBOR_CORE_POD,
                        [
                            "curl",
                            "-s",
                            "-o",
                            "/dev/null",
                            "-w",
                            "%{http_code}",
                            "http://localhost:8080/c/oidc/callback?error=test",
                        ],
                    )
                    test_results.append(f"Callback endpoint test: HTTP {callback_test}")

                    # Step 4: Verify OIDC is properly configured in database
                    db_check = self.k8s.exec_in_pod(
                        HARBOR_NAMESPACE,
                        HARBOR_DATABASE_POD,
                        [
                            "psql",
                            "-U",
                            POSTGRES_USER,
                            "-d",
                            REGISTRY_DB,
                            "-c",
                            "SELECT k, v FROM properties WHERE k LIKE '%oidc%' LIMIT 5;",
                        ],
                    )
                    test_results.append(f"Database OIDC Config:\n{db_check}")

                    # Step 5: Check if test user would be allowed (group membership)
                    group_check_cmd = f"""
from authentik.core.models import User, Group
user = User.objects.get(username='{test_username}')
groups = user.groups.all()
print(f'User groups: {{[g.name for g in groups]}}')
"""

                    try:
                        group_result = self.k8s.exec_in_pod(
                            AUTHENTIK_NAMESPACE,
                            self.k8s._get_first_pod_by_component(
                                AUTHENTIK_NAMESPACE, "server"
                            ),
                            ["python", "-c", group_check_cmd],
                        )
                        test_results.append(f"User Groups: {group_result}")
                    except Exception as e:
                        test_results.append(f"Group Check Failed: {e}")

                    # Summary
                    if "HTTP 302" in login_test and "400" in callback_test:
                        self.logger.info("✅ OIDC endpoints are responding correctly")
                    else:
                        self.logger.warning("⚠️ OIDC endpoints may have issues")

        except Exception as e:
            test_results.append(f"Test Failed: {e}")
            self.logger.error(f"❌ E2E test failed: {e}")

        # Write all test results
        self.writer.write_output(
            "\n".join(
                [
                    "=== OIDC E2E TEST RESULTS ===",
                    f"Test User: {test_username}",
                    f"Test Email: {test_email}",
                    f"Timestamp: {datetime.utcnow().isoformat()}",
                    "\n--- Test Results ---",
                    "\n".join(test_results),
                ]
            ),
            "e2e/oidc-test-results.txt",
            "OIDC E2E Test Results",
        )
