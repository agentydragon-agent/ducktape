"""Database collection for Harbor OIDC investigation."""

import asyncio

from ..config import (
    HARBOR_ADMIN_PASSWORD_KEY,
    HARBOR_DATABASE_POD,
    HARBOR_NAMESPACE,
    HARBOR_OIDC_SECRET,
    POSTGRES_USER,
    REGISTRY_DB,
)
from .base import BaseCollector


class DatabaseCollector(BaseCollector):
    """Collector for database information."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.admin_password = None

    async def collect(self) -> None:
        """Collect ALL database information."""
        self.logger.info("Collecting database information")

        # Get admin password from secret
        self.admin_password = self.k8s.get_secret_value(
            HARBOR_NAMESPACE, HARBOR_OIDC_SECRET, HARBOR_ADMIN_PASSWORD_KEY
        )

        # Database queries to run
        db_queries = [
            # (query, output_file, description, is_dump)
            (
                "SELECT k, v FROM properties WHERE k LIKE '%oidc%' OR k = 'auth_mode' ORDER BY k;",
                "harbor-oidc-config.txt",
                "Harbor OIDC Config",
                False,
            ),
            ("SELECT * FROM harbor_user;", "harbor-users.txt", "Harbor Users", False),
            (
                "SELECT * FROM oidc_user;",
                "harbor-oidc-users.txt",
                "Harbor OIDC Users",
                False,
            ),
            ("\\dt", "harbor-tables.txt", "Harbor Tables", False),
            (
                f"pg_dump -U {POSTGRES_USER} {REGISTRY_DB}",
                "harbor-dump.sql",
                "Harbor Database Dump",
                True,
            ),
        ]

        tasks = [
            self._run_database_query(
                HARBOR_NAMESPACE,
                HARBOR_DATABASE_POD,
                REGISTRY_DB,
                query,
                f"databases/{output_file}",
                description,
                is_dump=is_dump,
            )
            for query, output_file, description, is_dump in db_queries
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_database_query(
        self,
        namespace: str,
        pod: str,
        database: str,
        query: str,
        output_file: str,
        description: str,
        is_dump: bool = False,
    ) -> None:
        """Run a database query in a pod."""
        if is_dump:
            # For dumps, use shell to get FULL dump
            result = self.k8s.exec_in_pod(namespace, pod, ["sh", "-c", query])
        else:
            # Use the dedicated psql method for regular queries
            result = self.k8s.exec_psql(
                namespace, pod, query, database=database, user=POSTGRES_USER
            )

        # Write FULL unfiltered result
        self.write_output(result, output_file, description)

    def _ensure_admin_password(self) -> None:
        """Ensure admin password is loaded from secret."""
        if not self.admin_password:
            self.admin_password = self.k8s.get_secret_value(
                HARBOR_NAMESPACE, HARBOR_OIDC_SECRET, HARBOR_ADMIN_PASSWORD_KEY
            )
