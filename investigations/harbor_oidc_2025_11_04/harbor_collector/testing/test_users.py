"""Test user management for Authentik."""

from contextlib import contextmanager

from ..config import AUTHENTIK_NAMESPACE


class TestUserManager:
    """Manager for creating and cleaning up Authentik test users."""

    def __init__(self, k8s_client, logger):
        self.k8s = k8s_client
        self.logger = logger

    @contextmanager
    def authentik_test_user(self, username: str, password: str, email: str):
        """Context manager for creating and cleaning up Authentik test users."""
        server_pod = self.k8s._get_first_pod_by_component(AUTHENTIK_NAMESPACE, "server")
        user_created = False

        try:
            # Create user
            create_cmd = f"""
from authentik.core.models import User
user = User.objects.create_user(
    username='{username}',
    email='{email}',
    password='{password}'
)
user.save()
print(f'Created user: {{user.username}} (ID: {{user.pk}})')
"""
            result = self.k8s.exec_in_pod(
                AUTHENTIK_NAMESPACE,
                server_pod,
                ["python", "-c", create_cmd],
            )
            self.logger.info(f"✅ Created test user: {username}")
            user_created = True

            # Yield control back to the caller with the user info
            yield {
                "username": username,
                "password": password,
                "email": email,
                "creation_result": result,
            }

        finally:
            # Always attempt cleanup if user was created
            if user_created:
                self.logger.info(f"Cleaning up test user: {username}")
                cleanup_cmd = f"""
from authentik.core.models import User
deleted = User.objects.filter(username='{username}').delete()
print(f'Deleted {{deleted[0]}} users')
"""
                try:
                    cleanup_result = self.k8s.exec_in_pod(
                        AUTHENTIK_NAMESPACE,
                        server_pod,
                        ["python", "-c", cleanup_cmd],
                    )
                    self.logger.info(f"✅ Test user cleaned up: {cleanup_result}")
                except Exception as e:
                    self.logger.error(
                        f"❌ Failed to clean up test user {username}: {e}"
                    )
