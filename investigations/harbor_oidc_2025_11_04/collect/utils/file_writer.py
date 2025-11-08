"""File writing utilities for Harbor OIDC investigation."""

from datetime import datetime
from pathlib import Path


class FileWriter:
    """Utility for writing output files with metadata."""

    def __init__(self, base_dir: Path, logger):
        self.base_dir = base_dir
        self.logger = logger

    def write_output(
        self,
        content: str,
        output_file: str,
        description: str = "",
        command: str = "",
        exit_code: int = 0,
    ) -> None:
        """Write output to file with metadata."""
        output_path = self.base_dir / output_file
        output_path.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        if command:
            lines.append(f"# Command: {command}")
        lines.append(f"# Timestamp: {datetime.now()}")
        lines.append(f"# Exit Code: {exit_code}")
        if description:
            lines.append(f"# Description: {description}")
        lines.append("")
        lines.append(content)
        output_path.write_text("\n".join(lines))

        self.logger.info(f"✅ {description or 'Output'} saved to {output_file}")
