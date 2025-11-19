#!/usr/bin/env python3
"""Parallel wrapper for ansible-lint that reports serially.

Runs ansible-lint on multiple files in parallel using Python's concurrent.futures,
but outputs results sequentially for clean, non-interleaved output.
"""
import argparse
import os
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def run_ansible_lint(file_path: str, offline: bool, skip_schema_update: bool,
                     skip_vault: bool, config_file: str) -> tuple[str, int, str]:
    """Run ansible-lint on a single file.

    Returns:
        Tuple of (file_path, exit_code, output)
    """
    env = os.environ.copy()

    if skip_vault:
        env['ANSIBLE_LINT_SKIP_VAULT'] = '1'
    if skip_schema_update:
        env['ANSIBLE_LINT_SKIP_SCHEMA_UPDATE'] = '1'

    cmd = ['ansible-lint']

    if offline:
        cmd.append('--offline')

    if config_file:
        cmd.extend(['--config-file', config_file])

    cmd.append(file_path)

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
    parser = argparse.ArgumentParser(
        description='Run ansible-lint in parallel with serial output'
    )
    parser.add_argument(
        '--offline',
        action='store_true',
        help='Run ansible-lint with --offline flag (skip network operations)'
    )
    parser.add_argument(
        '--skip-schema-update',
        action='store_true',
        help='Set ANSIBLE_LINT_SKIP_SCHEMA_UPDATE=1'
    )
    parser.add_argument(
        '--skip-vault',
        action='store_true',
        default=True,
        help='Set ANSIBLE_LINT_SKIP_VAULT=1 (default: true)'
    )
    parser.add_argument(
        '--config-file',
        default='../.ansible-lint.yaml',
        help='Path to ansible-lint config file (default: ../.ansible-lint.yaml)'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Files to lint (if empty, lints all)'
    )

    args = parser.parse_args()

    # Change to ansible directory (where this script should be located)
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    # Get files, stripping "ansible/" prefix if present
    files = []
    for file_path in args.files:
        # Strip "ansible/" prefix that pre-commit might add
        stripped = file_path.removeprefix('ansible/')
        files.append(stripped)

    # If no files specified, run on all files (default behavior)
    if not files:
        env = os.environ.copy()
        if args.skip_vault:
            env['ANSIBLE_LINT_SKIP_VAULT'] = '1'
        if args.skip_schema_update:
            env['ANSIBLE_LINT_SKIP_SCHEMA_UPDATE'] = '1'

        cmd = ['ansible-lint']
        if args.offline:
            cmd.append('--offline')
        if args.config_file:
            cmd.extend(['--config-file', args.config_file])

        result = subprocess.run(cmd, env=env, check=False)
        sys.exit(result.returncode)

    # Single file: run directly without parallelism overhead
    if len(files) == 1:
        _, exit_code, output = run_ansible_lint(
            files[0], args.offline, args.skip_schema_update,
            args.skip_vault, args.config_file
        )
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
            executor.submit(
                run_ansible_lint, file_path, args.offline,
                args.skip_schema_update, args.skip_vault, args.config_file
            ): file_path
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
