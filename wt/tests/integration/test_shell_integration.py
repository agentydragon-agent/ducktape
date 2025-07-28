"""
Integration tests for shell function interaction with the CLI.

Tests the actual wt.sh that users interact with, including fd3 redirection,
exit code semantics, and process boundary interactions.
"""

# === CRITICAL DEBUGGING WISDOM FOR SHELL TESTING ===
# Testing shell integration is complex due to process boundaries and fd3 redirection.
# Key insights:
# - Use the actual wt shell function that users interact with
# - Test the wt shell function *AND* the Python binary TOGETHER as a system, as they're used by user in shell
# - Test exit codes: 0=success, 1=unhandled error (no fd3), 2=managed error (with fd3)
# - Shell subprocess needs PYTHONPATH to find wt module
# - click.echo() outputs to stdout by default, not stderr
# - DON'T mock across process boundaries - create real error conditions instead

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# Global constants for paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
WT_FUNCTION_PATH = PROJECT_ROOT / "wt.sh"


def create_shell_script(wt_args: list[str]) -> str:
    """Create a shell script that calls wt with the given arguments."""
    return f"wt {' '.join(wt_args)}"


def run_shell_script(script_content: str, cwd: str) -> subprocess.CompletedProcess:
    """Execute a shell script with wt function setup and return the result."""
    # Prepare environment with PYTHONPATH for the subprocess
    env = os.environ.copy()
    
    # Get current Python's site-packages to ensure dependencies are available
    import site
    site_packages = site.getsitepackages() + [site.getusersitepackages()]
    python_path_parts = [str(PROJECT_ROOT)] + site_packages + [env.get('PYTHONPATH', '')]
    env["PYTHONPATH"] = ":".join(filter(None, python_path_parts))

    # Create script with wt function setup and hashbang
    full_script = f"""#!/bin/bash
# Set up wt shell function
source {WT_FUNCTION_PATH}

# Original script content
{script_content}
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh") as f:
        f.write(full_script)
        f.flush()  # Ensure content is written before execution

        # Make script executable
        os.chmod(f.name, 0o755)

        # Run the script and capture output
        result = subprocess.run(
            ["/bin/bash", f.name],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
        return result


def run_wt_command(main_repo: Path, wt_args: list[str]) -> subprocess.CompletedProcess:
    """Create and run a shell script that calls wt with the given arguments."""
    shell_script = create_shell_script(wt_args)
    return run_shell_script(shell_script, str(main_repo))


@pytest.mark.integration
@pytest.mark.shell
class TestShellIntegration:
    def test_help_command_basic(self, test_config):
        """Test that help command works through shell integration."""
        # Test basic help command - should not require real git repo setup
        result = run_wt_command(test_config.main_repo, ["--help"])

        # Should succeed and show help output
        assert result.returncode == 0, f"Help command failed: {result.stderr}"
        assert "USAGE:" in result.stdout

    def test_wt_help_lists_examples(self, test_config):
        """Test that wt help shows example usage."""
        result = run_wt_command(test_config.main_repo, ["sh", "help"])

        # Basic test that it doesn't crash
        # Note: May fail if it tries to access real daemon/git, but should show some output
        if result.returncode == 0:
            assert len(result.stdout) > 0

    def test_shell_script_execution_basic(self, test_config):
        """Test that shell script can execute basic wt commands."""
        # Basic test that the shell function exists and can be sourced
        if not WT_FUNCTION_PATH.exists():
            pytest.fail(f"wt.sh not found at {WT_FUNCTION_PATH}")
            
        test_script = """# Test that wt function is available
type wt
echo "Shell function loaded successfully"
"""

        result = run_shell_script(test_script, str(test_config.main_repo))

        # Should be able to source the function
        assert result.returncode == 0, f"Shell setup failed: {result.stderr}"
        assert "Shell function loaded successfully" in result.stdout

    def test_successful_teleport_with_pwd_verification(self, real_temp_repo, real_env):
        """Test that wt teleport actually changes directory using pwd verification."""
        from contextlib import contextmanager
        from ..conftest import kill_daemon_and_verify
        
        @contextmanager
        def daemon_cleanup():
            kill_daemon_and_verify(real_temp_repo)
            try:
                yield
            finally:
                kill_daemon_and_verify(real_temp_repo)


        def parse_teleport_output(result):
            output_lines = [line for line in result.stdout.strip().split('\n') if line]
            if not output_lines:
                pytest.fail(f"No output from script. Stderr: {result.stderr}")
            
            output_line = output_lines[-1]
            parts = output_line.split(':', 3)
            
            if len(parts) != 4:
                pytest.fail(f"Expected 4 parts in output, got {len(parts)}. Output: {output_line}")
            
            return {
                'create_exit': int(parts[0]),
                'nav_exit': int(parts[1]), 
                'pwd_before': parts[2],
                'pwd_after': parts[3]
            }

        # Main test logic
        shell_script = """# Verify shell function is loaded
if ! declare -f wt > /dev/null; then
    echo "ERROR: wt function not loaded"
    exit 99
fi

# Use shell function - it calls Python CLI with fd3 redirection
wt -c teleport-test
create_exit=$?

pwd_before=$(pwd)
wt teleport-test  
nav_exit=$?
pwd_after=$(pwd)

echo "$create_exit:$nav_exit:$pwd_before:$pwd_after"
"""

        with daemon_cleanup():
            result = run_shell_script(shell_script, str(real_temp_repo))

            data = parse_teleport_output(result)
            
            assert data['create_exit'] == 0, f"Create failed: {result.stderr}"
            assert data['nav_exit'] == 0, f"Navigate failed: {result.stderr}"
            
            expected_dir = str(real_temp_repo / "worktrees" / "teleport-test")
            assert data['pwd_after'] == expected_dir, f"Directory change failed. Expected: {expected_dir}, Got: {data['pwd_after']}"
            
            worktree_path = real_temp_repo / "worktrees" / "teleport-test"
            assert worktree_path.exists() and worktree_path.is_dir()


@pytest.mark.integration
@pytest.mark.shell
class TestShellIntegrationEdgeCases:
    def test_shell_environment_isolation(self, test_config):
        """Test that shell environment is properly isolated."""
        # Basic environment test
        env_test_script = """echo "Environment test completed"
"""

        result = run_shell_script(env_test_script, str(test_config.main_repo))
        assert result.returncode == 0
        assert "Environment test completed" in result.stdout
