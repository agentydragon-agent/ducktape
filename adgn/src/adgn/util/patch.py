"""
Patch utilities:
- apply_unified_patch: single-file unified diff applied to a string (using our multi-file applier under the hood)
- apply_patch_auto: dispatch OpenAI patch envelope vs multi-file unified diff and apply via IO callbacks
"""

from __future__ import annotations

from collections.abc import Callable

from unidiff import PatchSet

from adgn.third_party.openai_cookbook.apply_patch import (
    identify_files_needed as oc_identify_files_needed,
    process_patch as oc_process_patch,
)
from adgn.util.unified_patch import apply_unified_diff, normalize_single_file_unified_patch

# Canonical error message when patches must modify exactly one file
SINGLE_FILE_REQUIRED_ERR = "patch must modify exactly one file"


def apply_unified_patch(original: str, patch_text: str) -> str:
    """Apply a single-file unified diff patch to original and return the result.

    For multi-file patches, use apply_patch_auto with IO callbacks.
    """
    written: dict[str, str] = {}

    def _open_fn(_path: str) -> str:
        return original

    def _write_fn(path: str, content: str) -> None:
        written[path] = content

    def _remove_fn(path: str) -> None:
        written[path] = ""

    apply_unified_diff(patch_text, _open_fn, _write_fn, _remove_fn)
    if not written:
        return original
    return next(iter(written.values()))


def apply_patch_auto(
    patch_text: str,
    open_fn: Callable[[str], str],
    write_fn: Callable[[str, str], None],
    remove_fn: Callable[[str], None],
    *,
    require_single_file: bool | None = None,
) -> tuple[dict[str, str], set[str]]:
    s = patch_text.lstrip()
    written: dict[str, str] = {}
    removed: set[str] = set()

    def _wrap_write(path: str, content: str) -> None:
        write_fn(path, content)
        written[path] = content

    def _wrap_remove(path: str) -> None:
        remove_fn(path)
        removed.add(path)

    if s.startswith("*** Begin Patch"):
        files = oc_identify_files_needed(patch_text)
        if require_single_file and len(files) != 1:
            raise ValueError(SINGLE_FILE_REQUIRED_ERR)
        oc_process_patch(patch_text, open_fn, _wrap_write, _wrap_remove)
    else:
        pt = normalize_single_file_unified_patch(patch_text)
        if require_single_file:
            data = [ln.encode("utf-8") for ln in pt.splitlines(True)]
            pset = PatchSet(data, encoding="utf-8")
            if len(pset) != 1:
                raise ValueError(SINGLE_FILE_REQUIRED_ERR)
        apply_unified_diff(pt, open_fn, _wrap_write, _wrap_remove)

    if require_single_file:
        touched = set(written.keys()) | removed
        if len(touched) != 1:
            raise ValueError(SINGLE_FILE_REQUIRED_ERR)
    return written, removed
