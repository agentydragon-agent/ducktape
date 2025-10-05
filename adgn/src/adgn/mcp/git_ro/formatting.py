"""Formatting and pagination utilities for git-ro server.

Contains lightweight Pydantic models for paginated text and list responses,
and helpers to convert pygit2 data structures into typed outputs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
import pygit2

# -------------------------- shared slicing -----------------------------------


class TextSlice(BaseModel):
    offset_chars: int = Field(
        default=0,
        ge=0,
        description="Start offset into output (characters)",
    )
    max_chars: int = Field(
        default=200_000,
        gt=0,
        le=500_000,
        description="Maximum characters to return (cap 500k)",
    )


class TextPage(BaseModel):
    body: str
    truncated: bool
    next_offset: int | None = None
    total_chars: int


def apply_text_slice(body: str, sl: TextSlice) -> TextPage:
    start = max(0, int(sl.offset_chars))
    end = max(start, start + int(sl.max_chars))
    total = len(body)
    sliced = body[start:end]
    return TextPage(
        body=sliced,
        truncated=(total > end),
        next_offset=(end if total > end else None),
        total_chars=total,
    )


# -------------------------- list pagination ----------------------------------


class ListSlice(BaseModel):
    offset: int = Field(
        default=0,
        ge=0,
        description="Start index for list pagination (>=0)",
    )
    limit: int = Field(
        default=1000,
        gt=0,
        le=5000,
        description="Maximum number of items to return (cap 5000)",
    )


class StringListPage(BaseModel):
    items: list[str]
    truncated: bool
    next_offset: int | None = None
    total_count: int


def apply_list_slice(all_items: list[str], sl: ListSlice) -> StringListPage:
    total = len(all_items)
    start = sl.offset
    end = min(total, start + sl.limit)
    items = all_items[start:end]
    truncated = end < total
    next_offset = end if truncated else None
    return StringListPage(
        items=items,
        truncated=truncated,
        next_offset=next_offset,
        total_count=total,
    )


def paginate_items(
    items_names: tuple[list[Any], list[str]],
    sl: ListSlice,
) -> tuple[list[Any], StringListPage]:
    items, names = items_names
    page = apply_list_slice(names, sl)
    start = sl.offset
    end = start + sl.limit
    return items[start:end], page


# -------------------------- structured diff outputs --------------------------


class DiffFileStat(BaseModel):
    status: str  # A/M/D/R/C/T
    path: str
    additions: int
    deletions: int
    rename_from: str | None = None
    rename_to: str | None = None


class DiffStatPage(BaseModel):
    items: list[DiffFileStat]
    truncated: bool
    next_offset: int | None = None
    total_count: int


class ChangedFile(BaseModel):
    status: str
    path: str
    rename_from: str | None = None
    rename_to: str | None = None


class ChangedFilesPage(BaseModel):
    items: list[ChangedFile]
    truncated: bool
    next_offset: int | None = None
    total_count: int


class StatusEntry(BaseModel):
    path: str
    index: str
    worktree: str


class StatusPage(BaseModel):
    entries: list[StatusEntry]
    truncated: bool
    next_offset: int | None = None
    total_count: int


# Map pygit2 delta statuses -> single-letter codes (like git --name-status)
STATUS_MAP: dict[int, str] = {
    pygit2.GIT_DELTA_ADDED: "A",
    pygit2.GIT_DELTA_MODIFIED: "M",
    pygit2.GIT_DELTA_DELETED: "D",
    pygit2.GIT_DELTA_RENAMED: "R",
    pygit2.GIT_DELTA_TYPECHANGE: "T",
}


def delta_to_changed_file(d: pygit2.DiffDelta) -> ChangedFile:
    status_char = STATUS_MAP.get(d.status, "?")
    old_path = d.old_file.path or None
    new_path = d.new_file.path or None
    path = new_path or old_path or ""
    return ChangedFile(
        status=status_char,
        path=path,
        rename_from=old_path if status_char == "R" else None,
        rename_to=new_path if status_char == "R" else None,
    )


def diff_to_changed_files(diff: pygit2.Diff) -> list[ChangedFile]:
    return [delta_to_changed_file(patch.delta) for patch in diff]


def diff_to_file_stats(diff: pygit2.Diff) -> list[DiffFileStat]:
    stats: list[DiffFileStat] = []
    for patch in diff:
        cf = delta_to_changed_file(patch.delta)
        add = sum(1 for h in patch.hunks for ln in h.lines if ln.origin == "+")
        delete = sum(1 for h in patch.hunks for ln in h.lines if ln.origin == "-")
        stats.append(
            DiffFileStat(
                status=cf.status,
                path=cf.path,
                additions=add,
                deletions=delete,
                rename_from=cf.rename_from,
                rename_to=cf.rename_to,
            ),
        )
    return stats


def build_changed_files_page(items: list[ChangedFile], sl: ListSlice) -> ChangedFilesPage:
    sliced, page = paginate_items((items, [i.path for i in items]), sl)
    return ChangedFilesPage(
        items=sliced,
        truncated=page.truncated,
        next_offset=page.next_offset,
        total_count=page.total_count,
    )


def build_diff_stat_page(stats: list[DiffFileStat], sl: ListSlice) -> DiffStatPage:
    sliced, page = paginate_items((stats, [s.path for s in stats]), sl)
    return DiffStatPage(
        items=sliced,
        truncated=page.truncated,
        next_offset=page.next_offset,
        total_count=page.total_count,
    )


def build_status_page(entries: list[StatusEntry], sl: ListSlice) -> StatusPage:
    sliced, page = paginate_items((entries, [e.path for e in entries]), sl)
    return StatusPage(
        entries=sliced,
        truncated=page.truncated,
        next_offset=page.next_offset,
        total_count=page.total_count,
    )
