"""OIDC E2E testing for Harbor."""

from datetime import datetime
import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ..config import (
    AUTHENTIK_BASE_URL,
    AUTHENTIK_NAMESPACE,
    HARBOR_BASE_URL,
    HARBOR_DATABASE_POD,
    HARBOR_NAMESPACE,
    POSTGRES_USER,
    REGISTRY_DB,
)
from .test_users import TestUserManager


class OIDCFlowError(Exception):
    """Base exception for OIDC flow errors."""


class AuthenticationError(OIDCFlowError):
    """Authentication-specific errors."""


class RedirectError(OIDCFlowError):
    """Redirect handling errors."""


class LoggingHTTPAdapter(HTTPAdapter):
    """HTTP adapter that logs all requests and responses."""

    def __init__(self, dumper_func, *args, **kwargs):
        """Initialize with a function to dump HTTP exchanges.

        Args:
            dumper_func: Function that takes (request, response, description) and logs them
        """
        self.dumper = dumper_func
        self._request_counter = 0
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        """Send request and log the exchange."""
        self._request_counter += 1
        description = (
            f"Request #{self._request_counter}: {request.method} {request.url}"
        )

        # Send the actual request
        response = super().send(request, **kwargs)

        # Log the exchange
        self.dumper(request, response, description)

        return response


class OIDCTester:
    """OIDC end-to-end testing."""

    def __init__(self, k8s_client, file_writer, logger):
        self.k8s = k8s_client
        self.writer = file_writer
        self.logger = logger
        self.test_user_manager = TestUserManager(k8s_client, logger)
        self.request_counter = 0
        self.session = None

    def _create_session(self) -> Session:
        """Create a requests session with retry strategy and logging adapter."""
        session = Session()
        session.verify = False  # Disable SSL verification for internal testing

        # Add retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        # Use our custom logging adapter
        adapter = LoggingHTTPAdapter(
            self._dump_http_exchange, max_retries=retry_strategy
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Enable redirect history tracking
        session.max_redirects = 10

        return session

    def _build_full_url(self, url: str) -> str:
        """Build full URL from potentially relative path."""
        if not url.startswith("http"):
            return f"{AUTHENTIK_BASE_URL}{url}"
        return url

    def _extract_flow_slug(self, url: str) -> Optional[str]:
        """Extract flow slug from Authentik URL."""
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip("/").split("/")

        for i, part in enumerate(path_parts):
            if part == "if" and i + 2 < len(path_parts) and path_parts[i + 1] == "flow":
                return path_parts[i + 2]

        return None

    def _parse_request_body(self, body) -> Optional[str]:
        """Parse request body to string."""
        if not body:
            return None

        try:
            if isinstance(body, bytes):
                return body.decode("utf-8")
            return str(body)
        except Exception:
            return "[Binary content]"

    def _parse_response_body(self, response: Response) -> dict[str, Any]:
        """Parse response body as JSON or text."""
        result = {}

        try:
            result["json"] = response.json()
        except Exception:
            try:
                result["text"] = response.text[:50000]  # Limit to 50KB
            except Exception:
                result["text"] = "[Binary or unparseable content]"

        return result

    def _dump_http_exchange(
        self,
        request: Optional[PreparedRequest],
        response: Optional[Response],
        description: str = "HTTP Exchange",
    ) -> str:
        """Dump HTTP exchange to file.

        Returns:
            Filename where exchange was saved
        """
        self.request_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        dump_data = {
            "timestamp": timestamp,
            "description": description,
            "request_number": self.request_counter,
        }

        # Add request details
        if request:
            dump_data["request"] = {
                "method": request.method,
                "url": request.url,
                "headers": dict(request.headers),
                "body": self._parse_request_body(request.body),
            }

        # Add response details
        if response:
            dump_data["response"] = {
                "status_code": response.status_code,
                "url": response.url,
                "headers": dict(response.headers),
                "cookies": response.cookies.get_dict(),
                "elapsed": str(response.elapsed),
                "encoding": response.encoding,
            }
            dump_data["response"].update(self._parse_response_body(response))

            # Add redirect history
            if response.history:
                dump_data["redirect_history"] = [
                    {
                        "status_code": hist.status_code,
                        "url": hist.url,
                        "headers": dict(hist.headers),
                    }
                    for hist in response.history
                ]

        # Save to file
        filename = f"e2e/http_exchange_{self.request_counter:03d}_{timestamp}.json"
        self.writer.write_output(
            json.dumps(dump_data, indent=2, default=str),
            filename,
            f"HTTP Exchange #{self.request_counter}: {description}",
        )

        return filename

    def _submit_username(
        self,
        session: Session,
        api_url: str,
        headers: dict[str, str],
        challenge: dict[str, Any],
        username: str,
    ) -> dict[str, Any]:
        """Submit username to Authentik flow.

        Returns:
            Next challenge response

        Raises:
            AuthenticationError: If username submission fails
        """
        if challenge.get("component") != "ak-stage-identification":
            raise AuthenticationError(
                f"Unexpected initial stage: {challenge.get('component')}"
            )

        payload = {
            "component": challenge.get("component"),
            "uid_field": username,
        }

        # Submit username - don't auto-follow redirects
        response = session.post(
            api_url, json=payload, headers=headers, allow_redirects=False
        )

        if response.status_code == 302:
            # Follow redirect manually
            next_url = response.headers.get("Location")
            if not next_url:
                raise RedirectError("No Location header in redirect response")

            next_url = self._build_full_url(next_url)
            next_response = session.get(next_url, headers=headers)

            if next_response.status_code != 200:
                raise AuthenticationError(
                    f"Failed to get password challenge: {next_response.status_code}"
                )

            return next_response.json()

        if response.status_code == 200:
            return response.json()

        raise AuthenticationError(f"Username submission failed: {response.status_code}")

    def _submit_password(
        self,
        session: Session,
        api_url: str,
        headers: dict[str, str],
        challenge: dict[str, Any],
        password: str,
    ) -> Response:
        """Submit password to Authentik flow.

        Returns:
            Password submission response

        Raises:
            AuthenticationError: If password submission fails
        """
        if challenge.get("component") != "ak-stage-password":
            raise AuthenticationError(
                "Password challenge not found after identification"
            )

        payload = {
            "component": challenge.get("component"),
            "password": password,
        }

        # Submit password - don't auto-follow redirects
        response = session.post(
            api_url, json=payload, headers=headers, allow_redirects=False
        )

        if response.status_code not in [200, 302]:
            raise AuthenticationError(
                f"Password submission failed: {response.status_code}"
            )

        return response

    def _handle_oauth_redirect(self, session: Session, response: Response) -> str:
        """Handle OAuth redirect after successful authentication.

        Returns:
            Result message
        """
        if response.status_code == 302:
            redirect_url = self._build_full_url(response.headers.get("Location", ""))
            final_response = session.get(redirect_url, allow_redirects=True)

            # Check for xak-flow-redirect
            try:
                json_response = final_response.json()
                if json_response.get("component") == "xak-flow-redirect":
                    redirect_to = self._build_full_url(json_response.get("to", ""))
                    oauth_response = session.get(redirect_to, allow_redirects=True)

                    if "/c/oidc/callback" in oauth_response.url:
                        if oauth_response.status_code == 200:
                            return "✅ OAuth2 flow completed successfully!"
                        error_body = (
                            oauth_response.text[:200]
                            if oauth_response.text
                            else "No response body"
                        )
                        return f"❌ Harbor callback failed: HTTP {oauth_response.status_code}, body: {error_body}"
                    if "/harbor/projects" in oauth_response.url:
                        if oauth_response.status_code == 200:
                            return "✅ OAuth2 flow completed - redirected to Harbor projects!"
                        return f"❌ Harbor projects page failed: HTTP {oauth_response.status_code}"
                    return f"❌ Unexpected OAuth destination: {oauth_response.url}"
            except Exception:
                # Not JSON response
                if "/c/oidc/callback" in final_response.url:
                    if final_response.status_code == 200:
                        return "✅ OAuth2 flow completed successfully!"
                    # Log the error response for debugging
                    error_body = (
                        final_response.text[:200]
                        if final_response.text
                        else "No response body"
                    )
                    return f"❌ Harbor callback failed: HTTP {final_response.status_code}, body: {error_body}"
                return f"❌ Unexpected final destination: {final_response.url}"

        # Handle JSON redirect response
        try:
            json_response = response.json()
            if json_response.get("type") == "redirect":
                redirect_to = json_response.get("to")
                if redirect_to == "/":
                    return "❌ Authentication succeeded but 'next' parameter was lost"
                return f"❌ Unexpected redirect target: {redirect_to}"
        except Exception:
            pass

        return f"❌ Unexpected response: {response.status_code}"

    async def _complete_oauth2_flow(
        self, harbor_pod_name, test_username, test_password
    ):
        """Execute complete OAuth2/OIDC authentication flow.

        Returns:
            List of result strings describing the flow execution
        """
        results = []
        self.request_counter = 0  # Reset counter for this test run

        # Setup logging
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("urllib3").setLevel(logging.DEBUG)

        # Create session with logging adapter
        session = self._create_session()

        try:
            # Step 1: Check Harbor pod connectivity
            self.logger.info("Checking Harbor core pod...")
            port_check = self.k8s.exec_in_pod(
                HARBOR_NAMESPACE,
                harbor_pod_name,
                [
                    "sh",
                    "-c",
                    "netstat -tlnp | grep :8080 || echo 'Port 8080 not bound'",
                ],
            )
            results.append(f"Harbor pod port check: {port_check}")

            # Step 2: Initiate OIDC login flow
            self.logger.info("Initiating Harbor OIDC login flow...")
            harbor_login_url = (
                f"{HARBOR_BASE_URL}/c/oidc/login?redirect_url=/harbor/projects"
            )
            login_response = session.get(harbor_login_url, allow_redirects=True)

            results.append(f"Final landing page status: {login_response.status_code}")
            results.append(f"Final URL: {login_response.url[:150]}")
            results.append(f"Redirect history: {len(login_response.history)} redirects")

            # Early bailout if login page not reached
            if login_response.status_code != 200:
                raise AuthenticationError(
                    f"Failed to reach login page, got {login_response.status_code}"
                )

            if "/if/flow/" not in login_response.url:
                raise AuthenticationError(
                    f"Not at login flow page, at: {login_response.url}"
                )

            # Extract flow slug
            flow_slug = self._extract_flow_slug(login_response.url)
            if not flow_slug:
                raise AuthenticationError("Could not extract flow slug from URL")

            results.append(f"Flow slug: {flow_slug}")

            # Build API URL with query parameters
            parsed_url = urlparse(login_response.url)
            api_url = f"{AUTHENTIK_BASE_URL}/api/v3/flows/executor/{flow_slug}/"
            if parsed_url.query:
                from urllib.parse import quote

                api_url += f"?query={quote(parsed_url.query)}"
                results.append(f"Query params preserved: {parsed_url.query[:100]}")

            # Setup headers for API interaction
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": AUTHENTIK_BASE_URL,
                "Referer": login_response.url,
            }

            csrf_token = session.cookies.get("authentik_csrf")
            if csrf_token:
                headers["X-authentik-CSRF"] = csrf_token
                results.append("CSRF token added to headers")

            # Get initial challenge
            self.logger.info("Getting initial flow challenge...")
            challenge_response = session.get(api_url, headers=headers)

            if challenge_response.status_code != 200:
                raise AuthenticationError(
                    f"Failed to get initial challenge: {challenge_response.status_code}"
                )

            challenge = challenge_response.json()
            results.append(f"Initial stage: {challenge.get('component', 'unknown')}")

            # Submit username
            self.logger.info("Submitting username...")
            results.append("Submitting username...")

            password_challenge = self._submit_username(
                session, api_url, headers, challenge, test_username
            )
            results.append(
                f"Next stage: {password_challenge.get('component', 'unknown')}"
            )

            # Submit password
            self.logger.info("Submitting password...")
            results.append("Submitting password...")

            pwd_response = self._submit_password(
                session, api_url, headers, password_challenge, test_password
            )
            results.append(f"Password submission: {pwd_response.status_code}")

            # Handle OAuth redirect
            oauth_result = self._handle_oauth_redirect(session, pwd_response)
            results.append(oauth_result)

        except AuthenticationError as e:
            results.append(f"❌ Authentication failed: {e}")
            self.logger.error(f"Authentication error: {e}")
        except RedirectError as e:
            results.append(f"❌ Redirect handling failed: {e}")
            self.logger.error(f"Redirect error: {e}")
        except Exception as e:
            results.append(f"❌ OAuth2 flow error: {e}")
            self.logger.error(f"OAuth2 flow exception: {e}")

        return results

    async def test_oidc_e2e_flow(self) -> None:
        """Test complete OIDC login flow end-to-end."""
        self.logger.info("Testing end-to-end OIDC flow")

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

                    # Step 2: Complete OAuth2 flow with real authentication
                    self.logger.info("Testing complete OIDC authentication flow...")

                    core_pod = self.k8s._get_first_pod_by_component(
                        HARBOR_NAMESPACE, "core"
                    )
                    if not core_pod:
                        test_results.append("ERROR: No Harbor core pod found")
                        self.logger.error("❌ No Harbor core pod found for OIDC test")
                    else:
                        # Execute complete OAuth2 flow
                        flow_result = await self._complete_oauth2_flow(
                            core_pod, test_username, test_password
                        )
                        test_results.extend(flow_result)

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

                    # Summary based on OAuth2 flow results - be EXPLICIT about success/failure
                    if any(
                        "✅ OAuth2 flow completed successfully!" in result
                        for result in flow_result
                    ):
                        self.logger.info(
                            "✅ OIDC authentication SUCCEEDED - user can log into Harbor via Authentik"
                        )
                    elif any(
                        "✅ Authentication successful, following callback..." in result
                        for result in flow_result
                    ):
                        # Auth worked but callback might have failed
                        if any(
                            "❌ Callback failed" in result for result in flow_result
                        ):
                            self.logger.error(
                                "❌ OIDC authentication FAILED - Authentik accepted credentials but Harbor callback rejected"
                            )
                        else:
                            self.logger.warning(
                                "⚠️ OIDC authentication PARTIAL - Authentik accepted credentials, Harbor callback status unknown"
                            )
                    else:
                        self.logger.error(
                            "❌ OIDC authentication FAILED - could not complete OAuth2 flow"
                        )

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
