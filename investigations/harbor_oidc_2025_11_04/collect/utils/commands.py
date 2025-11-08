"""Command execution utilities for Harbor OIDC investigation."""

from ..config import HARBOR_DATABASE_POD, HARBOR_NAMESPACE, POSTGRES_USER


class CommandRunner:
    """Utility for running commands in pods."""

    def __init__(self, k8s_client, file_writer, logger):
        self.k8s = k8s_client
        self.writer = file_writer
        self.logger = logger

    def run_pod_commands(
        self, namespace: str, pod: str, commands: list[tuple[str, str, str]]
    ) -> None:
        """Run multiple commands in a pod and save outputs."""
        for command, output_file, description in commands:
            cmd_to_run = ["sh", "-c", command] if isinstance(command, str) else command
            result = self.k8s.exec_in_pod(namespace, pod, cmd_to_run)
            if output_file:
                self.writer.write_output(result, output_file, description)
            else:
                self.logger.info(f"{description}: {result[:50]}...")

    def run_psql_commands(self, commands: list[str], log_results: bool = False) -> None:
        """Run PostgreSQL commands in the database pod."""
        cmd_list = [
            (f"psql -U {POSTGRES_USER} -c '{cmd}'", None, f"PostgreSQL: {cmd}")
            for cmd in commands
        ]
        self.run_pod_commands(HARBOR_NAMESPACE, HARBOR_DATABASE_POD, cmd_list)
