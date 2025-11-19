#!/usr/bin/env python3
"""Parallel wrapper for ansible-lint that reports serially.

Runs ansible-lint on multiple files in parallel using Python's concurrent.futures,
but outputs results sequentially for clean, non-interleaved output.
"""
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def run_ansible_lint(file_path: str) -> tuple[str, int, str]:
    """Run ansible-lint on a single file.

    Returns:
        Tuple of (file_path, exit_code, output)
    """
    env = os.environ.copy()
    env['ANSIBLE_LINT_SKIP_VAULT'] = '1'
    env['ANSIBLE_LINT_SKIP_SCHEMA_UPDATE'] = '1'

    cmd = [
        'ansible-lint',
        '--offline',
        '--config-file',
        '../.ansible-lint.yaml',
        file_path
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env
        )
        return (file_path, result.returncode, result.stdout + result.stderr)
    except Exception as e:
        return (file_path, 1, f"Error running ansible-lint on {file_path}: {e}\n")


def main():
    """Main entry point."""
    # Change to ansible directory
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Get files from command line, stripping "ansible/" prefix if present
    files = []
    for arg in sys.argv[1:]:
        # Strip "ansible/" prefix that pre-commit might add
        stripped = arg.removeprefix('ansible/')
        files.append(stripped)

    # If no files specified, run on all files (default behavior)
    if not files:
        env = os.environ.copy()
        env['ANSIBLE_LINT_SKIP_VAULT'] = '1'
        env['ANSIBLE_LINT_SKIP_SCHEMA_UPDATE'] = '1'

        result = subprocess.run(
            ['ansible-lint', '--offline', '--config-file', '../.ansible-lint.yaml'],
            env=env,
            check=False
        )
        sys.exit(result.returncode)

    # Single file: run directly without parallelism overhead
    if len(files) == 1:
        _, exit_code, output = run_ansible_lint(files[0])
        if output:
            print(output, end='')
        sys.exit(exit_code)

    # Multiple files: run in parallel, collect results in order
    results = {}
    max_exit_code = 0

    # Use ProcessPoolExecutor for true parallelism (not limited by GIL)
    with ProcessPoolExecutor() as executor:
        # Submit all tasks
        future_to_file = {
            executor.submit(run_ansible_lint, file_path): file_path
            for file_path in files
        }

        # Collect results as they complete
        for future in as_completed(future_to_file):
            file_path, exit_code, output = future.result()
            results[file_path] = (exit_code, output)
            max_exit_code = max(max_exit_code, exit_code)

    # Output results in original order (serial reporting)
    for file_path in files:
        if file_path in results:
            exit_code, output = results[file_path]
            if output:
                print(output, end='')

    sys.exit(max_exit_code)


if __name__ == '__main__':
    main()
