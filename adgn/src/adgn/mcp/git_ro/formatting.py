from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, Field
import pygit2

# -------------------------- pagination models -------------------------------


class ListSlice(BaseModel):
    offset: int = Field(default=0, ge=0, description="Start index of the window")
    limit: int = Field(default=100, ge=0, description="Max items to return (0 = unbounded)")


class TextSlice(BaseModel):
    offset_chars: int = Field(default=0, ge=0, description="Start character offset")
    max_chars: int = Field(default=0, ge=0, description="Max characters to return (0 = all)")


class TextPage(BaseModel):
    body: str
    total_chars: int
    truncated: bool
    next_offset: int | None = None


class StringListPage(BaseModel):
    items: list[str]
    total_items: int
    truncated: bool
    next_offset: int | None = None


T = TypeVar("T")


def _calc_window(total: int, start: int, size: int) -> tuple[int, int, bool, int | None]:
    """Core window math shared by list/text slicing.

    Returns (start, end, truncated, next_offset)."""
    s = max(0, start)
    e = min(total, s + size) if size and size > 0 else total
    truncated = e < total
    next_offset = e if truncated else None
    return s, e, truncated, next_offset


def apply_list_slice[T](items: Sequence[T], slicer: ListSlice) -> tuple[list[T], bool, int | None, int]:
    total = len(items)
    s, e, truncated, next_offset = _calc_window(total, slicer.offset, slicer.limit)
    return list(items[s:e]), truncated, next_offset, total


def apply_text_slice(body: str, slicer: TextSlice) -> TextPage:
    total = len(body)
    s, e, truncated, next_offset = _calc_window(total, slicer.offset_chars, slicer.max_chars)
    return TextPage(body=body[s:e], total_chars=total, truncated=truncated, next_offset=next_offset)


# -------------------------- status models -----------------------------------


class StatusEntry(BaseModel):
    path: str
    # Accept enum-to-str coercion from server module
    index: str = Field(description="Index status (e.g., M, A, D, R, T, ' ')")
    worktree: str = Field(description="Worktree status (e.g., M, D, ?, ' ')")


class StatusPage(BaseModel):
    entries: list[StatusEntry]
    truncated: bool
    next_offset: int | None = None
    total_entries: int


def build_status_page(entries: list[StatusEntry], slicer: ListSlice) -> StatusPage:
    window, truncated, next_offset, total = apply_list_slice(entries, slicer)
    return StatusPage(entries=window, truncated=truncated, next_offset=next_offset, total_entries=total)


# -------------------------- diff list (name-status) -------------------------


class ChangedFileItem(BaseModel):
    path: str
    status: str = Field(description="A (added), M (modified), D (deleted), R (renamed)")


class ChangedFilesPage(BaseModel):
    items: list[ChangedFileItem]
    truncated: bool
    next_offset: int | None = None
    total_items: int


def _status_char(delta_status: int) -> str:
    # Map pygit2 GIT_DELTA_* to a compact letter for name-status
    if delta_status == pygit2.GIT_DELTA_ADDED:
        return "A"
    if delta_status == pygit2.GIT_DELTA_DELETED:
        return "D"
    if delta_status == pygit2.GIT_DELTA_RENAMED:
        return "R"
    # Treat all others as modified (including copied, typechange, etc.)
    return "M"


def diff_to_changed_files(diff: pygit2.Diff) -> list[ChangedFileItem]:
    return [
        ChangedFileItem(
            path=((d.new_file.path or d.old_file.path) if d.new_file else d.old_file.path),
            status=_status_char(d.status),
        )
        for p in diff
        for d in [p.delta]
    ]


def build_changed_files_page(items: list[ChangedFileItem], slicer: ListSlice) -> ChangedFilesPage:
    window, truncated, next_offset, total = apply_list_slice(items, slicer)
    return ChangedFilesPage(items=window, truncated=truncated, next_offset=next_offset, total_items=total)


# -------------------------- diff stat (additions/deletions) -----------------


class StatItem(BaseModel):
    path: str
    additions: int
    deletions: int


class DiffStatPage(BaseModel):
    items: list[StatItem]
    truncated: bool
    next_offset: int | None = None
    total_items: int


def _count_patch_lines(patch: pygit2.Patch) -> tuple[int, int]:
    add = 0
    delete = 0
    for h in patch.hunks:
        for ln in h.lines:
            if ln.origin == "+":
                add += 1
            elif ln.origin == "-":
                delete += 1
    return add, delete


def diff_to_file_stats(diff: pygit2.Diff) -> list[StatItem]:
    out: list[StatItem] = []
    for patch in diff:  # type: ignore[assignment]  # pygit2.Diff iteration typing incomplete in stubs
        delta = patch.delta
        path = (delta.new_file.path or delta.old_file.path) if delta.new_file else delta.old_file.path
        additions, deletions = _count_patch_lines(patch)
        out.append(StatItem(path=path, additions=additions, deletions=deletions))
    return out


def build_diff_stat_page(items: list[StatItem], slicer: ListSlice) -> DiffStatPage:
    window, truncated, next_offset, total = apply_list_slice(items, slicer)
    return DiffStatPage(items=window, truncated=truncated, next_offset=next_offset, total_items=total)
