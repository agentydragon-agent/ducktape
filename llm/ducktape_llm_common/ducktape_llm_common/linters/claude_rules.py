"""Claude-specific linting rules enforcement using ruff and other tools.

This linter enforces rules from CLAUDE.md by tracking violation counts
and only complaining when counts increase.
"""

import ast
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import click
import pygit2

from ducktape_llm_common.linters.base import BaseLinter, LintError, LintResult
from ducktape_llm_common.linters.claude_config import (
    AutofixEntry,
    AutofixLog,
    ClaudeLinterConfig,
    FileViolations,
    LinterReport,
    ViolationDetail,
)


class ClaudeRulesLinter(BaseLinter):
    """Enforces Claude-specific coding rules from CLAUDE.md."""

    # Manual patterns for things ruff doesn't catch well
    MANUAL_PATTERNS = {
        "hasattr": r"\bhasattr\s*\(",  # No ruff rule for hasattr yet
        # Disabled for now:
        # 'noqa': r'#\s*noqa(?:\s|:|$)',
        # 'type-ignore': r'#\s*type:\s*ignore',
        # 'pylint-disable': r'#\s*pylint:\s*disable',
        # 'string-concat-url': r'["\']https?://["\'].*\+|\.format.*https?://',
        # 'string-concat-sql': r'(?i)(select|insert|update|delete|from|where).*["\'].*\+',
    }

    def __init__(
        self,
        session_pid: int | None = None,
        config: ClaudeLinterConfig | None = None,
        treat_all_as_errors: bool = False,
    ):
        """Initialize the Claude rules linter.

        Args:
            session_pid: Claude session PID for state tracking
            config: Linter configuration (will auto-load if not provided)
            treat_all_as_errors: If True, treat ALL violations as errors (not just new ones)
        """
        super().__init__()
        self.session_pid = session_pid or os.getppid()
        self.config = config or ClaudeLinterConfig.find_config()
        self.treat_all_as_errors = treat_all_as_errors

        # Remember where the linter was launched from
        self.launch_cwd = Path.cwd()

        # Get project directory for Claude's project scoping
        self.project_dir = self._get_project_dir()

        # State and log files under ~/.claude/projects/<project>/linter/
        self.claude_project_dir = self.get_claude_project_dir(self.project_dir, "linter")

        self._state_file = self.claude_project_dir / f"state_{self.session_pid}.json"
        self._state = self._load_state()

    def _get_project_dir(self) -> Path:
        """Get the project root directory (git root or cwd)."""
        try:
            # Try to find git repository
            repo_path = pygit2.discover_repository(str(Path.cwd()))
            if repo_path:
                repo = pygit2.Repository(repo_path)
                return Path(repo.workdir)
        except (pygit2.GitError, KeyError):
            pass
        return Path.cwd()

    @staticmethod
    def sanitize_project_path(path: Path) -> str:
        """Sanitize project path for use in filesystem (same as Claude uses)."""
        # Convert to absolute path and replace separators
        abs_path = path.resolve()
        # Replace path separators and colons with underscores
        sanitized = str(abs_path).replace("/", "_").replace("\\", "_").replace(":", "_")
        # Remove leading underscores
        return sanitized.lstrip("_")

    @staticmethod
    def get_claude_project_dir(project_path: Path, subdir: str = "linter") -> Path:
        """Get the full Claude project directory path.

        Args:
            project_path: The project root path
            subdir: Subdirectory under the Claude project (default: "linter")

        Returns:
            Full path to ~/.claude/projects/<sanitized_path>/<subdir>
        """
        sanitized = ClaudeRulesLinter.sanitize_project_path(project_path)
        claude_dir = Path.home() / ".claude" / "projects" / sanitized / subdir
        claude_dir.mkdir(parents=True, exist_ok=True)
        return claude_dir

    def _get_python_files(self, directory: Path) -> list[Path]:
        """Get Python files respecting .gitignore and excluding submodules.

        Only returns files under the CWD where the linter was launched from,
        even if the project directory is a parent of that CWD.
        """
        try:
            # Try to open git repository
            repo_path = pygit2.discover_repository(str(directory))
            if not repo_path:
                raise pygit2.GitError("Not a git repository")

            repo = pygit2.Repository(repo_path)
            workdir = Path(repo.workdir)

            # Get submodules to exclude
            submodule_paths = set()
            for submodule in repo.submodules:
                submodule_paths.add(submodule.path)

            files = []

            # Get files from git index (tracked files)
            for entry in repo.index:
                path = entry.path
                if path.endswith(".py"):
                    # Check if file is in a submodule
                    is_in_submodule = any(
                        path.startswith(sub_path + "/") or path == sub_path for sub_path in submodule_paths
                    )
                    if not is_in_submodule:
                        file_path = workdir / path
                        if file_path.exists():
                            # Only include files under launch CWD
                            try:
                                file_path.relative_to(self.launch_cwd)
                                files.append(file_path)
                            except ValueError:
                                # File is not under launch CWD, skip it
                                pass

            # Get untracked files using status
            status_dict = repo.status(untracked_files="all", ignored=False)
            for file_path_str, flags in status_dict.items():
                if flags & pygit2.GIT_STATUS_WT_NEW:  # Untracked file
                    if file_path_str.endswith(".py"):
                        # Check if file is in a submodule
                        is_in_submodule = any(
                            file_path_str.startswith(sub_path + "/") or file_path_str == sub_path
                            for sub_path in submodule_paths
                        )
                        if not is_in_submodule:
                            file_path = workdir / file_path_str
                            if file_path.exists():
                                # Check if ignored
                                if not repo.path_is_ignored(file_path_str):
                                    # Only include files under launch CWD
                                    try:
                                        file_path.relative_to(self.launch_cwd)
                                        files.append(file_path)
                                    except ValueError:
                                        # File is not under launch CWD, skip it
                                        pass

            return sorted(set(files))

        except (pygit2.GitError, KeyError):
            # Fallback to rglob if not in git repo
            files = []
            for file in directory.rglob("*.py"):
                # Skip if under .git directory
                if ".git" not in file.parts:
                    # Only include files under launch CWD
                    try:
                        file.relative_to(self.launch_cwd)
                        files.append(file)
                    except ValueError:
                        # File is not under launch CWD, skip it
                        pass
            return sorted(files)

    def _load_state(self) -> dict[str, dict]:
        """Load linter state from file."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def _save_state(self):
        """Save linter state to file."""
        with open(self._state_file, "w") as f:
            json.dump(self._state, f, indent=2)

    def _check_syntax(self, file: Path, content: str) -> LintError | None:
        """Check if Python file has valid syntax."""
        # Always check syntax regardless of rules since E999 was removed from ruff
        try:
            ast.parse(content, filename=str(file))
            return None
        except SyntaxError as e:
            return LintError(
                line=e.lineno or 1,
                column=e.offset or 1,
                message=f"Syntax error: {e.msg}",
                rule="syntax-error",
                file=file,
            )

    def _run_ruff(self, file: Path) -> dict[str, list[dict]]:
        """Run ruff on a file and parse results."""
        # Use rules from config
        select_rules = self.config.rules.enabled_rules

        if not select_rules:
            return {}

        try:
            cmd = [
                "ruff",
                "check",
                "--select",
                ",".join(select_rules),
                "--output-format",
                "json",
                str(file),
            ]

            if self.config.ruff_config_file:
                cmd.extend(["--config", self.config.ruff_config_file])

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.stdout:
                violations = json.loads(result.stdout)
                by_rule = defaultdict(list)
                for v in violations:
                    rule = v.get("code", "")
                    by_rule[rule].append(v)
                return dict(by_rule)
        except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
            pass

        return {}

    def _check_manual_patterns(self, file: Path, content: str) -> dict[str, list[tuple[int, int]]]:
        """Check patterns that ruff doesn't catch."""
        results = defaultdict(list)

        for line_num, line in enumerate(content.splitlines(), 1):
            # Check hasattr manually (no ruff rule for it)
            if self.config.rules.check_hasattr and re.search(self.MANUAL_PATTERNS["hasattr"], line):
                match = re.search(self.MANUAL_PATTERNS["hasattr"], line)
                if match:
                    results["hasattr"].append((line_num, match.start() + 1))

        return dict(results)

    def lint_file(self, file: Path) -> LintResult:
        """Lint a single Python file for Claude rule violations."""
        result = LintResult(file=file)

        if not self.config.enabled:
            return result

        # Check if file changed
        try:
            mtime = file.stat().st_mtime
        except OSError:
            return result

        file_key = str(file)
        file_state = self._state.get(file_key, {})
        last_check = file_state.get("last_check", 0)
        is_first_check = file_key not in self._state

        if mtime <= last_check:
            return result

        try:
            content = file.read_text()
        except UnicodeDecodeError as e:
            # Invalid unicode is a violation
            error = LintError(
                line=1,
                column=1,
                message=f"Invalid Unicode: {e}",
                rule="invalid-unicode",
                file=file,
            )
            result.errors.append(error)

            # Update state to record this error
            current_counts = {"invalid-unicode": 1}
            previous_counts = self._state.get(file_key, {}).get("violation_counts", {})

            # Only report if this is a new error
            if previous_counts.get("invalid-unicode", 0) == 0:
                self._state[file_key] = {
                    "last_check": mtime,
                    "last_check_time": datetime.now().isoformat(),
                    "violation_counts": current_counts,
                }
                self._save_state()
                return result
            else:
                # Already reported, clear errors
                result.errors.clear()
                return result
        except OSError as e:
            # Can't read file
            error = LintError(
                line=1,
                column=1,
                message=f"Cannot read file: {e}",
                rule="file-read-error",
                file=file,
            )
            result.errors.append(error)
            return result

        current_counts = {}
        all_violations: dict[str, list] = {}

        # Check syntax first
        syntax_error = self._check_syntax(file, content)
        if syntax_error:
            current_counts["syntax-error"] = 1
            all_violations["syntax-error"] = [syntax_error]

        # Run ruff
        ruff_violations = self._run_ruff(file)
        for rule_code, violations in ruff_violations.items():
            current_counts[rule_code] = len(violations)
            all_violations[rule_code] = violations

        # Check manual patterns
        manual_violations = self._check_manual_patterns(file, content)
        for pattern_name, locations in manual_violations.items():
            current_counts[pattern_name] = len(locations)
            all_violations[pattern_name] = locations

        # Compare with previous counts
        previous_counts = self._state.get(file_key, {}).get("violation_counts", {})

        # Report violations based on mode and whether this is first check
        for rule_name, current_count in current_counts.items():
            previous_count = previous_counts.get(rule_name, 0)

            # Determine if we should report this violation
            should_report_as_error = False
            if self.treat_all_as_errors and current_count > 0:
                # In treat_all_as_errors mode, report ALL violations as errors
                should_report_as_error = True
            elif is_first_check and current_count > 0 and not self.treat_all_as_errors:
                # First time seeing file - report as pre-existing warning
                self._add_pre_existing_warning(result, rule_name, current_count, all_violations.get(rule_name, []))
            elif current_count > previous_count:
                # New violations compared to last check
                should_report_as_error = True

            if should_report_as_error:
                # Add errors for violations
                if rule_name in manual_violations:
                    for line_num, column in manual_violations[rule_name]:
                        error = LintError(
                            line=line_num,
                            column=column,
                            message=f"{rule_name} violation",
                            rule=f"no-{rule_name}",
                            file=file,
                        )
                        result.errors.append(error)
                elif rule_name == "syntax-error" and syntax_error:
                    result.errors.append(syntax_error)
                else:
                    # Ruff violations
                    for v in all_violations.get(rule_name, []):
                        error = LintError(
                            line=v.get("location", {}).get("row", 0),
                            column=v.get("location", {}).get("column", 0),
                            message=f"{v.get('message', '')}",
                            rule=rule_name,
                            file=file,
                        )
                        result.errors.append(error)

        # Update state
        self._state[file_key] = {
            "last_check": mtime,
            "last_check_time": datetime.now().isoformat(),
            "violation_counts": current_counts,
        }
        self._save_state()

        return result

    def lint_directory(self, directory: Path, pattern: str = "*.py") -> list[LintResult]:
        """Lint all Python files in a directory recursively."""
        if not self.config.enabled:
            return []

        # Check if running under Claude (no TTY interaction)
        is_interactive = sys.stdout.isatty() and not os.environ.get("CLAUDE_CODE_SESSION")

        results = []
        start_time = time.time()

        if is_interactive:
            click.echo("Discovering Python files...")

        # Get list of Python files respecting gitignore
        # Always use launch CWD for file discovery, even if project dir is parent
        python_files = self._get_python_files(self.launch_cwd)

        if is_interactive and python_files:
            click.echo(f"Found {len(python_files)} Python files to check")
            click.echo(f"Scanning {len(python_files)} Python files...")

        for i, file in enumerate(python_files):
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > 10:
                click.secho(
                    f"\n❌ Timeout: Linting is taking too long ({elapsed:.1f}s)",
                    fg="red",
                    bold=True,
                )
                click.echo("Very large codebase? Slow filesystem? Network-mounted directories?")
                click.echo("\nPlease ask the user to:")
                click.echo("  1. Run from a faster location")
                click.echo("  2. Add more paths to .claude-linter.json ignore_paths")
                click.echo("  3. Use a more specific directory instead of repo root")
                sys.exit(1)

            # Skip config-based ignored paths
            if any(part in file.parts for part in self.config.ignore_paths):
                continue

            if is_interactive:
                # Show progress with spinner
                spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                spin_char = spinner[i % len(spinner)]
                progress = f"  {spin_char} Checking {i + 1}/{len(python_files)} files: {file.name[:30]}..."
                click.echo(f"\r{progress:<80}", nl=False)

            result = self.lint_file(file)
            if result.has_errors or result.has_warnings:
                results.append(result)

        if is_interactive and python_files:
            elapsed = time.time() - start_time
            click.echo(f"  ✓ Checked {len(python_files)} files in {elapsed:.1f}s          ")  # Clear line

        return results

    def format_violations(self, results: list[LintResult]) -> None:
        """Format violations for display using click."""
        if not results:
            return

        # Separate results with errors vs just warnings
        error_results = [r for r in results if r.has_errors]
        warning_results = [r for r in results if r.has_warnings and not r.has_errors]

        # Show warnings first (less severe)
        if warning_results:
            click.secho("=" * 40, fg="yellow")
            click.secho("⚠️  Pre-existing violations in inherited code", fg="yellow")
            click.secho("=" * 40, fg="yellow")
            click.echo()

            for result in warning_results:
                click.secho(f"⚠️  {result.file}", fg="yellow")
                for warning in result.warnings:
                    click.echo(f"   {warning.message}")
                click.echo()

            click.echo("These pre-existing violations don't need immediate fixing.")
            click.echo()

        # Show errors (new violations)
        if error_results:
            click.secho("=" * 40, fg="red", bold=True)
            click.secho("🚨 CLAUDE.md VIOLATIONS DETECTED! 🚨", fg="red", bold=True)
            click.secho("=" * 40, fg="red", bold=True)
            click.echo()

            for result in error_results:
                click.secho(f"❌ {result.file}", fg="red", bold=True)
                for i, error in enumerate(result.errors):
                    if i >= self.config.max_errors_per_file:
                        remaining = len(result.errors) - i
                        click.echo(f"   ... and {remaining} more violations")
                        break
                    click.echo(f"   Line {error.line}:{error.column} - {error.message}")
                click.echo()

            click.secho("🛑 EXECUTION BLOCKED - IMMEDIATE ACTION REQUIRED", fg="red", bold=True)
            click.echo()

            click.echo("1. STOP - Do not proceed")
            click.echo("2. ANALYZE - Why these violations occurred")
            click.echo("3. FIX - Create proper solutions")
            click.echo("4. PRESENT - Show plan to user")
            click.echo()

            click.secho("This pause is MANDATORY.", fg="red", bold=True)

    def check_and_block(self, directory: Path | None = None) -> bool:
        """Check for violations and block if found.

        Returns:
            True if safe to proceed, False if blocked
        """
        if directory is None:
            directory = Path.cwd()

        if not self.config.enabled:
            return True

        # Run autofixes first
        self._run_autofixes(directory)

        results = self.lint_directory(directory)

        if results:
            self.format_violations(results)

            # Check if we have actual errors (not just warnings)
            has_errors = any(r.has_errors for r in results)

            # Log violations to Claude project directory
            log_dir = self.claude_project_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"violations_{self.session_pid}.jsonl"

            # Also create full report for Claude to read
            report_file = log_dir / f"full_report_{self.session_pid}.json"
            self._dump_full_report(results, report_file)

            # Use JSON for the log file
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "session_pid": self.session_pid,
                "has_errors": has_errors,
                "summary": {
                    "total_files": len(results),
                    "files_with_errors": len([r for r in results if r.has_errors]),
                    "files_with_warnings": len([r for r in results if r.has_warnings]),
                    "total_errors": sum(len(r.errors) for r in results),
                    "total_warnings": sum(len(r.warnings) for r in results),
                },
                "files": [
                    {
                        "path": str(result.file),
                        "errors": len(result.errors),
                        "warnings": len(result.warnings),
                    }
                    for result in results
                ],
            }

            # Append to JSON lines format
            with open(log_file, "a") as f:
                f.write(json.dumps(log_data) + "\n")

            click.echo()
            click.secho(f"📄 Full report saved to: {report_file}", fg="yellow")
            click.echo("Claude can read this file for complete violation details.")

            # Only block if there are errors (not warnings)
            return not has_errors

        return True

    def _dump_full_report(self, results: list[LintResult], report_file: Path):
        """Dump full violation report to JSON file for Claude to read."""
        # Count violations by rule
        rule_counts: defaultdict[str, int] = defaultdict(int)
        for result in results:
            for error in result.errors:
                rule_counts[error.rule] += 1

        # Build file violations
        files = []
        for result in results:
            violations = [
                ViolationDetail(
                    line=error.line,
                    column=error.column,
                    rule=error.rule,
                    message=error.message,
                )
                for error in result.errors
            ]

            file_violations = FileViolations(
                path=str(result.file),
                violation_count=len(result.errors),
                violations=violations,
            )
            files.append(file_violations)

        # Create report
        report = LinterReport(
            timestamp=datetime.now(),
            session_pid=self.session_pid,
            total_files=len(results),
            total_violations=sum(len(r.errors) for r in results),
            violations_by_rule=dict(rule_counts),
            files=files,
        )

        # Save report using Pydantic
        report.to_json_file(report_file)

    def show_internal_state(self, directory: Path):
        """Show internal state without updating counters."""
        click.secho("=== Claude Linter Internal State ===", fg="cyan", bold=True)
        click.echo(f"Session PID: {self.session_pid}")
        click.echo(f"State file: {self._state_file}")
        click.echo()

        if not self._state:
            click.echo("No state recorded yet.")
            return

        # Group files by directory
        files_by_dir = defaultdict(list)
        for file_path in sorted(self._state.keys()):
            dir_path = Path(file_path).parent
            files_by_dir[dir_path].append(file_path)

        for dir_path, files in sorted(files_by_dir.items()):
            click.secho(f"\n📁 {dir_path}/", fg="blue", bold=True)

            for file_path in files:
                file_state = self._state[file_path]
                last_check_time = file_state.get("last_check_time", "never")
                violation_counts = file_state.get("violation_counts", {})

                # Get file name
                file_name = Path(file_path).name

                # Format last check time
                if last_check_time != "never":
                    try:
                        dt = datetime.fromisoformat(last_check_time)
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        time_str = last_check_time
                else:
                    time_str = "never"

                click.echo(f"  📄 {file_name}")
                click.echo(f"     Last checked: {time_str}")

                if violation_counts:
                    click.echo("     Violations:")
                    for rule, count in sorted(violation_counts.items()):
                        click.echo(f"       - {rule}: {count}")
                else:
                    click.echo("     No violations recorded")

    def _add_pre_existing_warning(self, result: LintResult, rule_name: str, count: int, violations: list):
        """Add warnings for pre-existing violations in newly checked files."""
        # Create a single warning for all violations of this type
        warning = LintError(
            line=1,
            column=1,
            message=f"PRE-EXISTING: {count} {rule_name} violation(s) found in inherited code",
            rule=f"pre-existing-{rule_name}",
            file=result.file,
        )
        result.warnings.append(warning)

    def _run_autofixes(self, directory: Path):
        """Run automatic fixes that don't require user confirmation."""
        autofix_report = []
        autofix_log = []  # Detailed log for JSON output
        start_time = time.time()

        # Check if running under Claude
        is_interactive = sys.stdout.isatty() and not os.environ.get("CLAUDE_CODE_SESSION")

        if is_interactive:
            click.echo("Running autofixes...")

        # Check for project formatter configuration
        has_pyproject = (directory / "pyproject.toml").exists()
        has_ruff_config = any((directory / f).exists() for f in ["ruff.toml", ".ruff.toml", "pyproject.toml"])

        # Run ruff format if available and configured
        if has_ruff_config or has_pyproject:
            try:
                # Get list of Python files first (respecting gitignore)
                # Always use launch CWD for file discovery
                python_files = self._get_python_files(self.launch_cwd)

                if is_interactive:
                    click.echo(f"  Running ruff format on {len(python_files)} files...")

                # Take snapshots before formatting
                file_snapshots = {}
                for py_file in python_files:
                    if any(part in py_file.parts for part in self.config.ignore_paths):
                        continue
                    try:
                        file_snapshots[py_file] = py_file.read_text()
                    except (OSError, UnicodeDecodeError):
                        pass

                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > 10:
                    click.secho(
                        f"\n❌ Timeout: Autofixes taking too long ({elapsed:.1f}s)",
                        fg="red",
                        bold=True,
                    )
                    click.echo("Please run linter on a smaller directory or disable autofixes.")
                    sys.exit(1)

                # Run ruff format (replaces black)
                # Run from launch_cwd so ruff finds the right config
                cmd = ["ruff", "format", "."]
                if is_interactive:
                    click.echo(f"    Command: {' '.join(cmd)} (in {self.launch_cwd})")

                    # Show what config ruff will use
                    config_check = subprocess.run(
                        ["ruff", "config"],
                        capture_output=True,
                        text=True,
                        cwd=self.launch_cwd,
                    )
                    if config_check.returncode == 0 and config_check.stdout:
                        # Extract line-length from config output
                        for line in config_check.stdout.splitlines():
                            if "line-length" in line:
                                click.echo(f"    Using config: {line.strip()}")
                                break

                result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.launch_cwd)
                if result.returncode == 0 and result.stdout:
                    formatted_files = [f for f in result.stdout.strip().split("\n") if f]
                    if formatted_files:
                        autofix_report.append(("formatting (ruff)", formatted_files))

                        # Capture after snapshots and create log entries
                        for file_str in formatted_files:
                            file_path = Path(file_str)
                            if file_path in file_snapshots:
                                try:
                                    after_content = file_path.read_text()
                                    if after_content != file_snapshots[file_path]:
                                        entry = AutofixEntry(
                                            file_path=str(file_path),
                                            timestamp=datetime.now(),
                                            fix_type="ruff format",
                                            before_snapshot=file_snapshots[file_path],
                                            after_snapshot=after_content,
                                            diff_summary="Formatted with ruff",
                                        )
                                        autofix_log.append(entry)
                                except (OSError, UnicodeDecodeError):
                                    pass
            except FileNotFoundError:
                pass

            try:
                # Run ruff fix for auto-fixable issues
                # Use the same rules from config
                select_rules = ",".join(self.config.rules.enabled_rules)
                cmd = [
                    "ruff",
                    "check",
                    "--select",
                    select_rules,
                    "--fix",
                    ".",
                ]

                if is_interactive:
                    click.echo("  Running ruff auto-fixes...")
                    click.echo(f"    Command: {' '.join(cmd)} (in {self.launch_cwd})")
                    click.echo(
                        f"    With rules: {select_rules[:100]}..."
                        if len(select_rules) > 100
                        else f"    With rules: {select_rules}"
                    )

                result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.launch_cwd)
                if result.returncode == 0 and "Fixed" in result.stderr:
                    # Parse fixed count from stderr
                    import re

                    match = re.search(r"Fixed (\d+) error", result.stderr)
                    if match:
                        autofix_report.append(("ruff auto-fixes", [f"{match.group(1)} errors fixed"]))
            except FileNotFoundError:
                pass

        # TODO: Remove black formatter code since ruff format replaces it
        # Ruff format is a drop-in replacement for black, so we don't need this anymore
        # Keeping commented out for now in case some projects still need black fallback

        # # Run black if no ruff format but black is configured
        # elif has_pyproject or has_pre_commit:
        #     try:
        #         if is_interactive:
        #             click.echo(f"  Running black formatter...")
        #
        #         cmd = ["black", str(self.launch_cwd)]
        #         if is_interactive:
        #             click.echo(f"    Command: {' '.join(cmd)}")
        #
        #         result = subprocess.run(cmd, capture_output=True, text=True)
        #         if result.returncode == 0 and "reformatted" in result.stderr:
        #             # Parse reformatted files from stderr
        #             reformatted = [
        #                 line
        #                 for line in result.stderr.split("\n")
        #                 if "reformatted" in line
        #             ]
        #             if reformatted:
        #                 autofix_report.append(("formatting (black)", reformatted))
        #     except FileNotFoundError:
        #         pass

        # Fix trailing whitespace (if not already handled by formatters)
        fixed_files = []
        try:
            # Try to use existing fix-unicode tool which also fixes whitespace
            result = subprocess.run(
                ["fix-unicode", "--fix-whitespace", str(self.launch_cwd)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout:
                fixed_files.extend(result.stdout.strip().split("\n"))
        except FileNotFoundError:
            # Fallback to simple Python implementation
            for py_file in self.launch_cwd.rglob("*.py"):
                if any(part in py_file.parts for part in self.config.ignore_paths):
                    continue

                try:
                    content = py_file.read_text()
                    lines = content.splitlines()
                    fixed_lines = [line.rstrip() for line in lines]

                    if lines != fixed_lines:
                        py_file.write_text("\n".join(fixed_lines) + "\n")
                        fixed_files.append(str(py_file))
                except (OSError, UnicodeDecodeError):
                    pass

        if fixed_files:
            autofix_report.append(("trailing whitespace", fixed_files))

        # Report all fixes
        if autofix_report:
            elapsed = time.time() - start_time
            click.echo(f"[Claude linter] FYI no action required. Autofixes applied in {elapsed:.1f}s:")
            for fix_type, items in autofix_report:
                if len(items) <= 3:
                    # Show all files inline
                    file_list = ", ".join(str(Path(item).resolve()) for item in items)
                    click.echo(f"  * {fix_type}: {file_list}")
                else:
                    # Show first 3 files inline and count
                    first_files = ", ".join(str(Path(item).resolve()) for item in items[:3])
                    click.echo(f"  * {fix_type}: {first_files}, ... and {len(items) - 3} more")
            click.echo()
        elif is_interactive:
            elapsed = time.time() - start_time
            click.echo(f"  No autofixes needed ({elapsed:.1f}s)")

        # Save detailed autofix log
        if autofix_log:
            log_dir = self.claude_project_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            autofix_log_file = (
                log_dir / f"autofix_log_{self.session_pid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

            log = AutofixLog(
                session_pid=self.session_pid,
                timestamp=datetime.now(),
                directory=str(directory),
                fixes=autofix_log,
            )
            log.to_json_file(autofix_log_file)

            click.secho(f"📝 Autofix log saved: {autofix_log_file}", fg="green")


@click.group(invoke_without_command=True)
@click.argument(
    "directory",
    default=".",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
)
@click.option(
    "--check-only",
    is_flag=True,
    help="Check without blocking (exit code indicates violations)",
)
@click.option("--init", is_flag=True, help="Initialize config for this project")
@click.option("--show-state", is_flag=True, help="Show internal state (counters, last seen times)")
@click.option(
    "--bash-hook", "bash_hook_flag", is_flag=True, help="Output bash hook logic for pre-command linter integration."
)
@click.pass_context
def main(ctx: click.Context, directory: Path, check_only: bool, init: bool, show_state: bool, bash_hook_flag: bool):
    """Claude rules linter - enforces CLAUDE.md coding standards."""
    if bash_hook_flag:
        _bash_hook()
        sys.exit(0)
    if init:
        config = ClaudeLinterConfig(enabled=True)
        config_file = Path.cwd() / ".claude-linter.json"
        config.to_json_file(config_file)
        click.secho(f"✅ Created {config_file}", fg="green")
        click.echo("Edit this file to customize rules.")
        sys.exit(0)

    linter = ClaudeRulesLinter()

    if show_state:
        linter.show_internal_state(directory)
        sys.exit(0)

    if check_only:
        results = linter.lint_directory(directory)
        if results:
            linter.format_violations(results)
            sys.exit(1)
        else:
            if linter.config.enabled:
                click.secho("✅ No violations found!", fg="green")
            else:
                click.echo("ℹ️  Linter not enabled. Use --init to create config.")
        sys.exit(0)

    if not linter.check_and_block(directory):
        sys.exit(1)
    sys.exit(0)


def _bash_hook() -> None:
    """Output bash hook logic for pre-command linter integration."""
    import importlib.resources as _resources

    hook = _resources.read_text(__package__, "bash_hook.sh")
    click.echo(hook)


if __name__ == "__main__":
    main()
