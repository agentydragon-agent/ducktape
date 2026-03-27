"""Interface library for running pre-commit hooks programmatically.

Wraps pre-commit's Python internals to provide structured per-hook results
without subprocess calls or stdout parsing. All pre-commit imports are
confined to this module.
"""

from __future__ import annotations

import contextlib
import difflib
import logging
import os
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from pre_commit.all_languages import languages
from pre_commit.clientlib import load_config
from pre_commit.commands.run import Classifier
from pre_commit.constants import CONFIG_FILE
from pre_commit.repository import all_hooks, install_hook_envs
from pre_commit.store import Store

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _chdir(path: Path) -> Generator[None]:
    """Temporarily change working directory, restoring on exit."""
    saved = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(saved)


@dataclass
class HookResult:
    hook_id: str
    hook_name: str
    output: bytes
    files_modified: bool
    exit_code: int
    auto_applied: bool = False
    rerun_exit_code: int | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.files_modified


@dataclass
class RunResult:
    hooks: list[HookResult] = field(default_factory=list)
    report_only_diff: list[str] = field(default_factory=list)

    @property
    def failed_hooks(self) -> list[HookResult]:
        """Hooks that failed and were NOT auto-applied."""
        return [h for h in self.hooks if not h.passed and not h.auto_applied]

    @property
    def auto_applied_results(self) -> list[HookResult]:
        return [h for h in self.hooks if h.auto_applied]

    @property
    def all_passed(self) -> bool:
        """True when all hooks either passed or were auto-applied."""
        return all(h.passed or h.auto_applied for h in self.hooks)


def _run_hooks(
    file_path: Path, project_dir: Path, auto_apply_hooks: Iterable[str] = ()
) -> tuple[list[HookResult], list[str]]:
    """Run all applicable pre-commit hooks on a single file.

    Two-phase execution:
    1. Auto-apply hooks run first (in original order), changes kept on disk.
    2. Report-only hooks run second (in original order) on the auto-applied
       result. Their cumulative diff is captured, then changes are reverted.

    Returns (hook_results, report_only_diff_lines).
    """
    auto_apply = set(auto_apply_hooks)
    config_path = project_dir / CONFIG_FILE

    store = Store()
    config = load_config(str(config_path))
    hooks = [h for h in all_hooks(config, store) if not h.stages or "pre-commit" in h.stages]
    if not hooks:
        return [], []

    install_hook_envs(hooks, store)

    rel_path = str(file_path.relative_to(project_dir))
    classifier = Classifier([rel_path])

    # Partition hooks into auto-apply and report-only, preserving relative order.
    auto_hooks = []
    report_hooks = []
    for hook in hooks:
        filenames = tuple(classifier.filenames_for_hook(hook))
        if not filenames and not hook.always_run:
            continue
        if hook.id in auto_apply:
            auto_hooks.append((hook, filenames))
        else:
            report_hooks.append((hook, filenames))

    results: list[HookResult] = []

    # Phase 1: auto-apply hooks — keep their changes, re-run to verify satisfaction.
    for hook, filenames in auto_hooks:
        content_before = file_path.read_bytes()
        language = languages[hook.language]
        run_kwargs = {
            "prefix": hook.prefix,
            "entry": hook.entry,
            "args": hook.args,
            "file_args": filenames if hook.pass_filenames else (),
            "is_local": hook.src == "local",
            "require_serial": hook.require_serial,
            "color": False,
        }
        with language.in_env(hook.prefix, hook.language_version):
            retcode, out = language.run_hook(**run_kwargs)
        current = file_path.read_bytes()
        modified = current != content_before

        # Re-run to check if the hook is now satisfied after auto-apply.
        rerun_retcode = None
        if modified:
            with language.in_env(hook.prefix, hook.language_version):
                rerun_retcode, _ = language.run_hook(**run_kwargs)
            rerun_content = file_path.read_bytes()
            if rerun_content != current:
                file_path.write_bytes(current)
        results.append(
            HookResult(
                hook_id=hook.id,
                hook_name=hook.name,
                output=out,
                files_modified=modified,
                exit_code=retcode,
                auto_applied=modified,
                rerun_exit_code=rerun_retcode if modified else None,
            )
        )

    # Phase 2: report-only hooks — capture diff, then revert.
    baseline = file_path.read_bytes()
    for hook, filenames in report_hooks:
        content_before = file_path.read_bytes()
        language = languages[hook.language]
        with language.in_env(hook.prefix, hook.language_version):
            retcode, out = language.run_hook(
                hook.prefix,
                hook.entry,
                hook.args,
                filenames if hook.pass_filenames else (),
                is_local=hook.src == "local",
                require_serial=hook.require_serial,
                color=False,
            )
        current = file_path.read_bytes()
        modified = current != content_before
        results.append(
            HookResult(hook_id=hook.id, hook_name=hook.name, output=out, files_modified=modified, exit_code=retcode)
        )

    # Compute diff of what report-only hooks would change, then revert.
    after_all = file_path.read_bytes()
    diff_lines: list[str] = []
    if after_all != baseline:
        baseline_lines = baseline.decode(errors="replace").splitlines(keepends=True)
        after_lines = after_all.decode(errors="replace").splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(baseline_lines, after_lines))
        file_path.write_bytes(baseline)

    return results, diff_lines


def run_on_file(file_path: Path, project_dir: Path, auto_apply_hooks: Iterable[str] = ()) -> RunResult:
    """Run pre-commit hooks on a single file using the Python API.

    Auto-apply hooks keep their modifications on disk. All other hooks'
    modifications are reverted. On crash, restores original content.
    """
    original_content = file_path.read_bytes()

    # pre-commit's internals assume cwd is the project root:
    # Classifier uses relative paths and hooks inherit process cwd
    # via subprocess.Popen (no cwd= parameter).
    try:
        with _chdir(project_dir):
            hook_results, diff_lines = _run_hooks(file_path, project_dir, auto_apply_hooks)
    except Exception:
        file_path.write_bytes(original_content)
        raise

    return RunResult(hooks=hook_results, report_only_diff=diff_lines)
