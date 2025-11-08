"""Base collector class for Harbor OIDC investigation."""

from ..k8s_client import K8sClient
from ..utils.file_writer import FileWriter


class BaseCollector:
    """Base class for all collectors."""

    def __init__(self, k8s_client: K8sClient, file_writer: FileWriter, logger):
        self.k8s = k8s_client
        self.writer = file_writer
        self.logger = logger
        self.base_dir = file_writer.base_dir

    def write_output(
        self, content: str, output_file: str, description: str = "", **kwargs
    ) -> None:
        """Convenience method to write output."""
        self.writer.write_output(content, output_file, description, **kwargs)

    async def collect(self) -> None:
        """Main collection method to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement collect()")
