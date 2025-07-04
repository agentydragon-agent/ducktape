import datetime
import subprocess
import tempfile
from pathlib import Path

import yaml


class PreCommitRunner:
    """Runner for pre-commit hooks based on provided config.

    This simplified version works both in and out of git repositories
    by using pre-commit's native capabilities.
    """

    def __init__(self, config):
        self.config = config

    def run(self, paths, cwd=None):
        """Run pre-commit hooks on specified paths.

        Args:
            paths: List of file paths to check
            cwd: Working directory (defaults to current directory)

        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        # Ensure cwd is set
        current_working_dir = Path(cwd) if cwd else Path.cwd()

        # Create log file
        log_dir = Path.home() / ".cache" / "claude-linter"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"debug-{datetime.datetime.now().isoformat()}.log"

        # Create a temporary git repo to make pre-commit happy
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # Initialize a git repo
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmpdir, capture_output=True)

            # Copy files to temp repo
            temp_paths = []
            for path in paths:
                path = Path(path)
                if path.is_absolute():
                    # Make it relative to the original cwd
                    try:
                        rel_path = path.relative_to(current_working_dir)
                    except ValueError:
                        # If not relative to cwd, just use the name
                        rel_path = Path(path.name)
                else:
                    rel_path = path

                temp_file = tmpdir_path / rel_path
                temp_file.parent.mkdir(parents=True, exist_ok=True)
                temp_file.write_text(path.read_text())
                temp_paths.append(str(rel_path))

            # Always use the config as-is (always fix=True)
            config = self.config

            # Write config file
            config_path = tmpdir_path / ".pre-commit-config.yaml"
            config_text = yaml.dump(config)
            config_path.write_text(config_text)

            # Write debug info to log
            with open(log_file, "w") as f:
                f.write("=== Claude Linter Debug Log ===\n")
                f.write(f"Time: {datetime.datetime.now()}\n")
                f.write(f"Working dir: {current_working_dir}\n")
                f.write(f"Temp dir: {tmpdir}\n")
                f.write(f"Paths: {paths}\n")
                f.write(f"Temp paths: {temp_paths}\n")
                f.write(f"\n--- Config ---\n{config_text}\n")

                # Write file contents
                f.write("\n--- File contents ---\n")
                for temp_path in temp_paths:
                    file_path = tmpdir_path / temp_path
                    f.write(f"\n{temp_path}:\n")
                    if file_path.exists():
                        f.write(file_path.read_text())
                    else:
                        f.write("(file does not exist)\n")

            # Stage files
            subprocess.run(["git", "add"] + temp_paths, cwd=tmpdir, capture_output=True)

            # Build command
            cmd = [
                "pre-commit",
                "run",
                "--all-files",  # Safe since we're in a temp dir with only our files
                "--verbose",
                # Use default stage (pre-commit)
            ]

            # Run as subprocess
            result = subprocess.run(cmd, cwd=tmpdir, capture_output=True, text=True)

            # Append results to log
            with open(log_file, "a") as f:
                f.write("\n--- Pre-commit command ---\n")
                f.write(f"Command: {' '.join(cmd)}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"\n--- Stdout ---\n{result.stdout}\n")
                f.write(f"\n--- Stderr ---\n{result.stderr}\n")

            # Copy modified files back
            for rel_path_str in temp_paths:
                temp_file = tmpdir_path / rel_path_str
                if temp_file.exists():
                    # Copy back to original location
                    original_path = Path(paths[temp_paths.index(rel_path_str)])
                    original_path.write_text(temp_file.read_text())

            return result.returncode, result.stdout, result.stderr
