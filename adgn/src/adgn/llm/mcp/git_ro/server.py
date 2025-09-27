"""
FastMCP server: Read-only Git tools (status, diff, log, show, rev-parse, ls-files, branches).

Design
- Explicit allowlist of read-only tools; no write/mutating operations are implemented
- Worktree-aware scoping: callers pass a worktree_root (Path). We execute libgit2 operations
  under that worktree (equivalent intent to `git -C <worktree_root> ...`). Works for normal repos
  and Git worktrees (where .git is a gitdir pointer file).
- Scope enforcement: worktree_root must resolve under one of configured allowed_roots to prevent
  path traversal/symlink escape. We also validate via pygit2.discover_repository.
- Typed Pydantic input/outputs provide precise JSON Schemas (better LLM tool-calling).
- Large output resilience: tools that can emit large text support TextSlice pagination and
  return TextPage with truncated/next_offset/total_chars metadata.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from adgn.llm.mcp._shared.fastmcp_helpers import SafeFastMCP
from adgn.llm.mcp._shared.fastmcp_helpers import mcp_flat_model
from pydantic import BaseModel, Field
import pygit2
from pygit2 import enums as git_enums

# Shared server name constant for clients/tests
GIT_RO_SERVER_NAME = "git-ro"

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


# -------------------------- helpers -----------------------------------------


def _open_repo(root: Path) -> pygit2.Repository:
    gitdir = pygit2.discover_repository(str(root))
    if not gitdir:
        raise ValueError(f"Not a git repository: {root}")
    return pygit2.Repository(gitdir)


def get_oid(obj: Any):
    """Return a pygit2.Oid from an object that may have .oid or .id."""
    return obj.oid if hasattr(obj, "oid") else obj.id


# -------------------------- inputs ------------------------------------------


class StatusInput(BaseModel):
    """Empty input model for git_status (keeps single-arg typed pattern consistent)."""

    pass


class DiffFormat(StrEnum):
    PATCH = "patch"
    NAME_STATUS = "name-status"
    STAT = "stat"


class DiffInput(BaseModel):
    format: DiffFormat = Field(
        default=DiffFormat.PATCH,
        description='Output format: "patch" | "name-status" | "stat"',
    )
    staged: bool = Field(
        default=False,
        description="If true, diff --cached (staged changes)",
    )
    unified: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Context lines (-U<N>) for patch format (0..1000; 0 shows only headers/hunks)",
    )
    rev_a: str | None = Field(
        default=None,
        description="Left side rev for range diff (e.g., HEAD^)",
    )
    rev_b: str | None = Field(
        default=None,
        description="Right side rev for range diff (e.g., HEAD)",
    )
    paths: list[str] | None = Field(
        default=None,
        description="Optional pathspecs to limit diff",
    )
    find_renames: bool = Field(default=True, description="Detect renames (-M)")
    slice: TextSlice = Field(
        default_factory=TextSlice,
        description="Pagination for patch output (format=patch; max_chars<=500k)",
    )
    list_slice: ListSlice = Field(
        default_factory=lambda: ListSlice(),
        description="Pagination for list outputs (name-status/stat; limit<=5000)",
    )


class LogInput(BaseModel):
    rev: str = Field(
        default="HEAD",
        description="Revision or range (e.g., HEAD, HEAD~10..HEAD)",
    )
    max_count: int = Field(default=50, description="Maximum number of entries")
    oneline: bool = Field(default=True, description="Format each commit as one line")
    slice: TextSlice = Field(
        default_factory=TextSlice,
        description="Pagination controls for large outputs",
    )


class ShowInput(BaseModel):
    object: str = Field(
        description="Object spec, e.g., HEAD, <sha>, or REV:PATH for blob content",
    )
    format: DiffFormat = Field(
        default=DiffFormat.PATCH,
        description='Output format: "patch" | "name-status" | "stat" (patch for blobs)',
    )
    slice: TextSlice = Field(
        default_factory=TextSlice,
        description="Pagination for patch/blob text outputs",
    )
    list_slice: ListSlice = Field(
        default_factory=lambda: ListSlice(),
        description="Pagination for list outputs (name-status/stat)",
    )


class RevParseInput(BaseModel):
    arg: str = Field(
        default="HEAD",
        description="Argument to rev-parse (e.g., HEAD, --show-toplevel)",
    )
    short: bool = Field(default=False, description="If true, shorten OIDs")


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
    """Convert a pygit2.Diff to a flat list of ChangedFile entries.

    Shared between git_diff(format=name-status) and git_show(format=name-status).
    """
    return [delta_to_changed_file(patch.delta) for patch in diff]


def diff_to_file_stats(diff: pygit2.Diff) -> list[DiffFileStat]:
    """Convert a pygit2.Diff to per-file stat entries (additions/deletions).

    Shared between git_diff(format=stat) and git_show(format=stat).

    Note: pygit2's Patch objects may not expose per-file additions/deletions totals
    reliably across versions. Compute counts by walking hunk lines and tallying
    origins ('+' for insertions, '-' for deletions).
    """
    stats: list[DiffFileStat] = []
    for patch in diff:
        cf = delta_to_changed_file(patch.delta)
        add = 0
        delete = 0
        try:
            for h in getattr(patch, "hunks", []) or []:
                for ln in getattr(h, "lines", []) or []:
                    origin = getattr(ln, "origin", None)
                    if origin == "+":
                        add += 1
                    elif origin == "-":
                        delete += 1
        except Exception:
            # Fallback to any attributes if available
            add = int(getattr(patch, "additions", 0) or 0)
            delete = int(getattr(patch, "deletions", 0) or 0)
        stats.append(
            DiffFileStat(
                status=cf.status,
                path=cf.path,
                additions=int(add),
                deletions=int(delete),
                rename_from=cf.rename_from,
                rename_to=cf.rename_to,
            ),
        )
    return stats


def build_changed_files_page(
    items: list[ChangedFile],
    sl: ListSlice,
) -> ChangedFilesPage:
    """Paginate ChangedFile items into a ChangedFilesPage."""
    sliced, page = paginate_items((items, [i.path for i in items]), sl)
    return ChangedFilesPage(
        items=sliced,
        truncated=page.truncated,
        next_offset=page.next_offset,
        total_count=page.total_count,
    )


def build_diff_stat_page(stats: list[DiffFileStat], sl: ListSlice) -> DiffStatPage:
    """Paginate DiffFileStat items into a DiffStatPage."""
    sliced, page = paginate_items((stats, [s.path for s in stats]), sl)
    return DiffStatPage(
        items=sliced,
        truncated=page.truncated,
        next_offset=page.next_offset,
        total_count=page.total_count,
    )


class RevParseResult(BaseModel):
    kind: str  # "oid" | "toplevel"
    value: str


class LsFilesInput(BaseModel):
    cached: bool = Field(
        default=False,
        description="List index entries (same as non-cached here); kept for parity",
    )
    list_slice: ListSlice = Field(
        default_factory=lambda: ListSlice(),
        description="Pagination controls for file lists",
    )


class BranchListInput(BaseModel):
    remote: bool = Field(
        default=False,
        description="List remote branches instead of local",
    )
    list_slice: ListSlice = Field(
        default_factory=lambda: ListSlice(),
        description="Pagination controls for branch lists",
    )


# Structured diff listing inputs/outputs
class DiffListInput(BaseModel):
    staged: bool = Field(
        default=False,
        description="If true, examine staged (index) changes; else worktree",
    )
    paths: list[str] | None = Field(
        default=None,
        description="Optional pathspecs to limit the diff",
    )
    find_renames: bool = Field(
        default=True,
        description="Detect renames (diff.find_similar)",
    )
    list_slice: ListSlice = Field(
        default_factory=lambda: ListSlice(),
        description="Pagination controls for file lists",
    )


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


class LogEntriesInput(BaseModel):
    rev: str = Field(default="HEAD", description="Revision to start from (e.g., HEAD)")
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of commits to skip (pagination offset)",
    )
    limit: int = Field(default=50, gt=0, le=1000, description="Max commits to return")
    include_message: bool = Field(
        default=False,
        description="Include full commit message body",
    )


class CommitEntry(BaseModel):
    id: str
    summary: str
    author_name: str
    author_email: str
    commit_time: int
    message: str | None = None


class LogEntriesPage(BaseModel):
    entries: list[CommitEntry]
    truncated: bool
    next_offset: int | None = None


# Discriminated unions for outputs (explicit output schema)
class PatchResult(TextPage):
    type: Literal["patch"] = "patch"


class NameStatusResult(ChangedFilesPage):
    type: Literal["name-status"] = "name-status"


class StatResult(DiffStatPage):
    type: Literal["stat"] = "stat"


DiffResult = Annotated[
    PatchResult | NameStatusResult | StatResult,
    Field(discriminator="type"),
]


# Show discriminated union (explicit output schema)
class ShowPatchResult(TextPage):
    type: Literal["patch"] = "patch"
    commit_id: str | None = None
    author_name: str | None = None
    author_email: str | None = None
    message: str | None = None


class ShowNameStatusResult(ChangedFilesPage):
    type: Literal["name-status"] = "name-status"


class ShowStatResult(DiffStatPage):
    type: Literal["stat"] = "stat"


ShowResult = Annotated[
    ShowPatchResult | ShowNameStatusResult | ShowStatResult,
    Field(discriminator="type"),
]

# -------------------------- outputs -----------------------------------------


class IndexStatus(StrEnum):
    NONE = " "
    M = "M"
    A = "A"
    D = "D"
    R = "R"
    T = "T"


class WorktreeStatus(StrEnum):
    NONE = " "
    M = "M"
    D = "D"
    UNTRACKED = "?"


class StatusEntry(BaseModel):
    path: str
    index: IndexStatus  # one of IndexStatus
    worktree: WorktreeStatus  # one of WorktreeStatus


class StatusPage(BaseModel):
    entries: list[StatusEntry]


# -------------------------- server ------------------------------------------


@dataclass
class GitRoState:
    git_repo: Path


def make_git_ro_server(git_repo: Path, *, name: str = "git-ro") -> SafeFastMCP:
    """Create a read-only Git FastMCP server scoped to a single allowed root.

    Guidance:
    - Pass a specific repository/worktree root (the directory containing your working tree).
    - For worktrees, use the worktree directory (the one containing the .git file pointing to
      .../.git/worktrees/<name>). The server runs libgit2 operations relative to worktree_root.

    Only non-mutating tools are registered. Any attempt to pass a worktree_root outside the
    configured root results in an error.
    """
    state = GitRoState(git_repo=git_repo.resolve())
    mcp = SafeFastMCP(
        name, instructions=f"Read-only Git tools scoped to repo: {git_repo}"
    )

    @mcp_flat_model(
        mcp,
        name="git_status",
        title="Git status",
        description="Compact status similar to porcelain v1",
        structured_output=True,
    )
    def git_status(input: StatusInput) -> StatusPage:
        """Return compact status entries similar to porcelain v1 (no headers)."""
        root = state.git_repo
        repo = _open_repo(root)
        st = repo.status()
        entries: list[StatusEntry] = []
        for path, flags in st.items():
            # Map pygit2 status flags to porcelain-like two-letter codes
            idx: IndexStatus = IndexStatus.NONE
            wt: WorktreeStatus = WorktreeStatus.NONE
            if flags & pygit2.GIT_STATUS_INDEX_NEW:
                idx = IndexStatus.A
            elif flags & pygit2.GIT_STATUS_INDEX_MODIFIED:
                idx = IndexStatus.M
            elif flags & pygit2.GIT_STATUS_INDEX_DELETED:
                idx = IndexStatus.D
            elif flags & pygit2.GIT_STATUS_INDEX_RENAMED:
                idx = IndexStatus.R
            elif flags & pygit2.GIT_STATUS_INDEX_TYPECHANGE:
                idx = IndexStatus.T
            if flags & pygit2.GIT_STATUS_WT_MODIFIED:
                wt = WorktreeStatus.M
            elif flags & pygit2.GIT_STATUS_WT_DELETED:
                wt = WorktreeStatus.D
            elif flags & pygit2.GIT_STATUS_WT_NEW:
                wt = WorktreeStatus.UNTRACKED
            entries.append(StatusEntry(path=path, index=idx, worktree=wt))
        return StatusPage(entries=entries)

    @mcp_flat_model(
        mcp,
        name="git_diff",
        title="Git diff",
        description="Diff with multiple formats",
        structured_output=True,
    )
    async def git_diff(input: DiffInput) -> DiffResult:
        """Git diff with multiple formats:
        - format=patch: unified patch (TextPage)
        - format=name-status: file status listing (ChangedFilesPage)
        - format=stat: per-file additions/deletions (DiffStatPage)
        """
        repo = _open_repo(state.git_repo)
        # Build base diff using repository-level APIs that match type stubs
        # Optional path filtering for large diffs (batch per file/group upstream)
        diff_kwargs = {}
        if input.paths:
            diff_kwargs["paths"] = input.paths
        if input.staged:
            a = None if repo.head_is_unborn else repo.head.target
            diff = repo.diff(a, None, cached=True, **diff_kwargs)
        else:
            diff = repo.index.diff_to_workdir(repo, **diff_kwargs)

        if input.find_renames:
            diff.find_similar()

        if input.format == DiffFormat.PATCH:
            patch_text = await asyncio.to_thread(lambda: diff.patch or "")
            page = apply_text_slice(patch_text, input.slice)
            return PatchResult(**page.model_dump())
        if input.format == DiffFormat.NAME_STATUS:
            items = await asyncio.to_thread(diff_to_changed_files, diff)
            page = build_changed_files_page(items, input.list_slice)
            return NameStatusResult(**page.model_dump())
        # STAT
        stats = await asyncio.to_thread(diff_to_file_stats, diff)
        page = build_diff_stat_page(stats, input.list_slice)
        return StatResult(**page.model_dump())

    @mcp_flat_model(
        mcp,
        name="git_log",
        title="Git log text",
        description="Return recent commits as text",
        structured_output=True,
    )
    def git_log(input: LogInput) -> TextPage:
        """Return recent commits as oneline entries or multi-line blocks, with pagination."""
        root = state.git_repo
        repo = _open_repo(root)
        if repo.head_is_unborn:
            return apply_text_slice("", input.slice)
        obj = repo.revparse_single(input.rev)
        head_oid = get_oid(obj)
        lines: list[str] = []
        walker = repo.walk(head_oid)
        for i, c in enumerate(walker, start=1):
            if input.oneline:
                summary = (c.message or "").splitlines()[0]
                lines.append(f"{str(c.id)[:7]} {summary}")
            else:
                lines.append(
                    f"commit {c.id}\nAuthor: {c.author.name} <{c.author.email}>\nDate:   {c.commit_time}\n\n{c.message or ''}\n",
                )
            if i >= input.max_count:
                break
        body = "\n".join(lines)
        if body and not body.endswith("\n"):
            body += "\n"
        return apply_text_slice(body, input.slice)

    @mcp_flat_model(
        mcp,
        name="git_log_entries",
        title="Git log entries",
        description="Structured commit entries with pagination",
        structured_output=True,
    )
    def git_log_entries(input: LogEntriesInput) -> LogEntriesPage:
        """Return structured commit entries with offset/limit pagination (preferred for programmatic use)."""
        root = state.git_repo
        repo = _open_repo(root)
        if repo.head_is_unborn:
            return LogEntriesPage(entries=[], truncated=False, next_offset=None)
        obj = repo.revparse_single(input.rev)
        head_oid = get_oid(obj)
        walker = repo.walk(head_oid)
        # Skip offset
        for i, _ in enumerate(walker):
            if i >= input.offset:
                break
        # Collect up to limit
        entries: list[CommitEntry] = []
        for i, c in enumerate(walker, start=1):
            msg = (c.message or None) if input.include_message else None
            entries.append(
                CommitEntry(
                    id=str(c.id),
                    summary=(c.message or "").splitlines()[0] if c.message else "",
                    author_name=c.author.name,
                    author_email=c.author.email,
                    commit_time=c.commit_time,
                    message=msg,
                ),
            )
            if i >= input.limit:
                break
        # Peek one more to determine truncation
        more = next(iter(walker), None)
        truncated = more is not None
        next_offset = input.offset + input.limit if truncated else None
        return LogEntriesPage(
            entries=entries,
            truncated=truncated,
            next_offset=next_offset,
        )

    @mcp_flat_model(
        mcp,
        name="git_show",
        title="Git show",
        description="Show commit or blob with multiple formats",
        structured_output=True,
    )
    async def git_show(input: ShowInput) -> ShowResult:
        """Show a commit in various formats or blob contents for REV:PATH.
        - format=patch: header + patch (TextPage) or blob text
        - format=name-status: file status listing (ChangedFilesPage)
        - format=stat: per-file additions/deletions (DiffStatPage)
        """
        root = state.git_repo
        repo = _open_repo(root)
        objspec = input.object
        # Blob contents: REV:PATH always as text
        if ":" in objspec:
            rev, path = objspec.split(":", 1)
            root_obj = repo.revparse_single(rev)
            tree = (
                root_obj.tree
                if isinstance(root_obj, pygit2.Commit)
                else root_obj.peel(pygit2.Tree)
            )
            cur: pygit2.Tree = tree
            for part in filter(None, path.split("/")):
                entry = cur[part]
                if entry.filemode == pygit2.GIT_FILEMODE_TREE:
                    cur = repo[entry.id].peel(pygit2.Tree)
                else:
                    blob = repo[entry.id].peel(pygit2.Blob)
                    data = blob.data
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        text = f"[binary blob {len(data)} bytes]"
                    page = apply_text_slice(text, input.slice)
                    return ShowPatchResult(**page.model_dump())
            raise FileNotFoundError(f"Path not found: {path}")
        obj_any = repo.revparse_single(objspec)
        # Narrow runtime types explicitly and bind to a typed local variable so mypy can follow.
        if isinstance(obj_any, pygit2.Tag):
            maybe_commit = obj_any.peel(pygit2.Commit)
        elif isinstance(obj_any, pygit2.Commit):
            maybe_commit = obj_any
        else:
            raise TypeError(
                f"Unexpected git object type for {objspec}: {type(obj_any)!r}",
            )
        obj: pygit2.Commit = cast(pygit2.Commit, maybe_commit)

        # Build commit diff against first parent (or empty tree)
        if obj.parent_ids:
            parent = repo[obj.parent_ids[0]].peel(pygit2.Commit)
            diff = repo.diff(parent, obj)
        else:
            diff = repo.diff(None, obj)
        diff.find_similar()

        if input.format == DiffFormat.PATCH:
            patch_text = await asyncio.to_thread(lambda: diff.patch or "")
            page = apply_text_slice(patch_text, input.slice)
            return ShowPatchResult(
                **page.model_dump(),
                commit_id=str(obj.id),
                author_name=obj.author.name,
                author_email=obj.author.email,
                message=obj.message or None,
            )

        if input.format == DiffFormat.NAME_STATUS:
            items = await asyncio.to_thread(diff_to_changed_files, diff)
            page = build_changed_files_page(items, input.list_slice)
            return ShowNameStatusResult(**page.model_dump())

        # STAT
        stats = await asyncio.to_thread(diff_to_file_stats, diff)
        page = build_diff_stat_page(stats, input.list_slice)
        return ShowStatResult(**page.model_dump())

    @mcp_flat_model(
        mcp,
        name="git_rev_parse",
        title="Git rev-parse",
        description="Resolve rev or show-toplevel",
        structured_output=True,
    )
    def git_rev_parse(input: RevParseInput) -> RevParseResult:
        """Resolve a rev to an OID (optionally shortened) or return toplevel path for --show-toplevel."""
        root = state.git_repo
        repo = _open_repo(root)
        if input.arg == "--show-toplevel":
            return RevParseResult(
                kind="toplevel",
                value=str(Path(repo.workdir).resolve()),
            )
        obj = repo.revparse_single(input.arg)
        oid = get_oid(obj)
        s = str(oid)
        if input.short:
            s = s[:7]
        return RevParseResult(kind="oid", value=s)

    @mcp_flat_model(
        mcp,
        name="git_ls_files",
        title="Git ls-files",
        description="List index paths with pagination",
        structured_output=True,
    )
    def git_ls_files(input: LsFilesInput) -> StringListPage:
        """List index paths, with offset/limit pagination (structured output)."""
        root = state.git_repo
        repo = _open_repo(root)
        all_paths = [e.path for e in repo.index]
        return apply_list_slice(all_paths, input.list_slice)

    @mcp_flat_model(
        mcp,
        name="git_branch_list",
        title="Git branch list",
        description="List branches with pagination",
        structured_output=True,
    )
    def git_branch_list(input: BranchListInput) -> StringListPage:
        """List local or remote branches (short names) with offset/limit pagination (structured output)."""
        root = state.git_repo
        repo = _open_repo(root)
        kind = (
            git_enums.BranchType.REMOTE if input.remote else git_enums.BranchType.LOCAL
        )
        names = repo.listall_branches(kind)
        return apply_list_slice(names, input.list_slice)

    return mcp
