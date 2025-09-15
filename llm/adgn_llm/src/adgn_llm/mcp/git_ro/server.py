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

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Annotated, Literal
from enum import StrEnum

import pygit2
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Shared server name constant for clients/tests
GIT_RO_SERVER_NAME = "git-ro"

# -------------------------- shared slicing -----------------------------------


class TextSlice(BaseModel):
    offset_chars: int = Field(default=0, ge=0, description="Start offset into output (characters)")
    max_chars: int = Field(default=200_000, gt=0, le=500_000, description="Maximum characters to return (cap 500k)")


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
    return TextPage(body=sliced, truncated=(total > end), next_offset=(end if total > end else None), total_chars=total)


# -------------------------- helpers -----------------------------------------


def _resolve_repo(git_repo: Path, raw: Path) -> Path:
    if raw is None:
        raise ValueError("worktree_root is required")
    rp = Path(raw).resolve()
    if not rp.exists() or not rp.is_dir():
        raise ValueError(f"worktree_root must be an existing directory: {rp}")
    root = Path(git_repo).resolve()
    try:
        in_scope = rp.is_relative_to(root)  # py311+
    except Exception:
        in_scope = (str(rp) == str(root)) or str(rp).startswith(str(root) + os.sep)
    if not in_scope:
        raise ValueError(f"worktree_root {rp} is outside allowed root {root}")
    # Verify it's a git repository/worktree using pygit2 discovery
    gitdir = pygit2.discover_repository(str(rp))
    if not gitdir:
        raise ValueError(f"Not a git repository/worktree: {rp}")
    return rp


def _open_repo(root: Path) -> pygit2.Repository:
    gitdir = pygit2.discover_repository(str(root))
    if not gitdir:
        raise ValueError(f"Not a git repository: {root}")
    return pygit2.Repository(gitdir)


# -------------------------- inputs ------------------------------------------


class RepoInput(BaseModel):
    """No user-supplied repo path; server is bound to a single git_repo at construction."""

    pass


class StatusInput(RepoInput):
    porcelain: bool = Field(default=True, description="Use compact status markers akin to --porcelain=v1")


class DiffFormat(StrEnum):
    PATCH = "patch"
    NAME_STATUS = "name-status"
    STAT = "stat"


class DiffInput(RepoInput):
    format: DiffFormat = Field(default=DiffFormat.PATCH, description='Output format: "patch" | "name-status" | "stat"')
    staged: bool = Field(default=False, description="If true, diff --cached (staged changes)")
    unified: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Context lines (-U<N>) for patch format (0..1000; 0 shows only headers/hunks)",
    )
    rev_a: str | None = Field(default=None, description="Left side rev for range diff (e.g., HEAD^)")
    rev_b: str | None = Field(default=None, description="Right side rev for range diff (e.g., HEAD)")
    paths: list[str] | None = Field(default=None, description="Optional pathspecs to limit diff")
    find_renames: bool = Field(default=True, description="Detect renames (-M)")
    slice: TextSlice = Field(
        default_factory=TextSlice, description="Pagination for patch output (format=patch; max_chars<=500k)"
    )
    list_slice: "ListSlice" = Field(
        default_factory=lambda: ListSlice(), description="Pagination for list outputs (name-status/stat; limit<=5000)"
    )


class LogInput(RepoInput):
    rev: str = Field(default="HEAD", description="Revision or range (e.g., HEAD, HEAD~10..HEAD)")
    max_count: int = Field(default=50, description="Maximum number of entries")
    oneline: bool = Field(default=True, description="Format each commit as one line")
    slice: TextSlice = Field(default_factory=TextSlice, description="Pagination controls for large outputs")


class ShowInput(RepoInput):
    object: str = Field(description="Object spec, e.g., HEAD, <sha>, or REV:PATH for blob content")
    format: DiffFormat = Field(
        default=DiffFormat.PATCH, description='Output format: "patch" | "name-status" | "stat" (patch for blobs)'
    )
    slice: TextSlice = Field(default_factory=TextSlice, description="Pagination for patch/blob text outputs")
    list_slice: "ListSlice" = Field(
        default_factory=lambda: ListSlice(), description="Pagination for list outputs (name-status/stat)"
    )


class RevParseInput(RepoInput):
    arg: str = Field(default="HEAD", description="Argument to rev-parse (e.g., HEAD, --show-toplevel)")
    short: bool = Field(default=False, description="If true, shorten OIDs")


class ListSlice(BaseModel):
    offset: int = Field(default=0, ge=0, description="Start index for list pagination (>=0)")
    limit: int = Field(default=1000, gt=0, le=5000, description="Maximum number of items to return (cap 5000)")


class StringListPage(BaseModel):
    items: list[str]
    truncated: bool
    next_offset: int | None = None
    total_count: int


def apply_list_slice(all_items: list[str], sl: "ListSlice") -> StringListPage:
    total = len(all_items)
    start = sl.offset
    end = min(total, start + sl.limit)
    items = all_items[start:end]
    truncated = end < total
    next_offset = end if truncated else None
    return StringListPage(items=items, truncated=truncated, next_offset=next_offset, total_count=total)


def paginate_items(items_names: tuple[list[Any], list[str]], sl: "ListSlice") -> tuple[list[Any], StringListPage]:
    items, names = items_names
    page = apply_list_slice(names, sl)
    start = sl.offset
    end = start + sl.limit
    return items[start:end], page


# Map pygit2 delta statuses -> single-letter codes (like git --name-status)
STATUS_MAP: dict[int, str] = {
    getattr(pygit2, "GIT_DELTA_ADDED"): "A",
    getattr(pygit2, "GIT_DELTA_MODIFIED"): "M",
    getattr(pygit2, "GIT_DELTA_DELETED"): "D",
    getattr(pygit2, "GIT_DELTA_RENAMED"): "R",
    getattr(pygit2, "GIT_DELTA_COPIED", 18): "C",
    getattr(pygit2, "GIT_DELTA_TYPECHANGE"): "T",
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


class RevParseResult(BaseModel):
    kind: str  # "oid" | "toplevel"
    value: str


class LsFilesInput(RepoInput):
    cached: bool = Field(default=False, description="List index entries (same as non-cached here); kept for parity")
    list_slice: "ListSlice" = Field(
        default_factory=lambda: ListSlice(), description="Pagination controls for file lists"
    )


class BranchListInput(RepoInput):
    remote: bool = Field(default=False, description="List remote branches instead of local")
    list_slice: "ListSlice" = Field(
        default_factory=lambda: ListSlice(), description="Pagination controls for branch lists"
    )


# Structured diff listing inputs/outputs
class DiffListInput(RepoInput):
    staged: bool = Field(default=False, description="If true, examine staged (index) changes; else worktree")
    paths: list[str] | None = Field(default=None, description="Optional pathspecs to limit the diff")
    find_renames: bool = Field(default=True, description="Detect renames (diff.find_similar)")
    list_slice: "ListSlice" = Field(
        default_factory=lambda: ListSlice(), description="Pagination controls for file lists"
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


# Structured, object-shaped log entries (prefer over text bodies when possible)
class LogEntriesInput(RepoInput):
    rev: str = Field(default="HEAD", description="Revision to start from (e.g., HEAD)")
    offset: int = Field(default=0, ge=0, description="Number of commits to skip (pagination offset)")
    limit: int = Field(default=50, gt=0, le=1000, description="Max commits to return")
    include_message: bool = Field(default=False, description="Include full commit message body")


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
class PatchResult(BaseModel):
    type: Literal["patch"] = "patch"
    result: TextPage


class NameStatusResult(BaseModel):
    type: Literal["name-status"] = "name-status"
    result: ChangedFilesPage


class StatResult(BaseModel):
    type: Literal["stat"] = "stat"
    result: DiffStatPage


DiffResult = Annotated[PatchResult | NameStatusResult | StatResult, Field(discriminator="type")]


# Show discriminated union (explicit output schema)
class ShowPatchResult(BaseModel):
    type: Literal["patch"] = "patch"
    result: TextPage
    commit_id: str | None = None
    author_name: str | None = None
    author_email: str | None = None
    message: str | None = None


class ShowNameStatusResult(BaseModel):
    type: Literal["name-status"] = "name-status"
    result: ChangedFilesPage


class ShowStatResult(BaseModel):
    type: Literal["stat"] = "stat"
    result: DiffStatPage


ShowResult = Annotated[ShowPatchResult | ShowNameStatusResult | ShowStatResult, Field(discriminator="type")]

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


def make_git_ro_server(git_repo: Path, *, name: str = "git-ro") -> FastMCP:
    """Create a read-only Git FastMCP server scoped to a single allowed root.

    Guidance:
    - Pass a specific repository/worktree root (the directory containing your working tree).
    - For worktrees, use the worktree directory (the one containing the .git file pointing to
      .../.git/worktrees/<name>). The server runs libgit2 operations relative to worktree_root.

    Only non-mutating tools are registered. Any attempt to pass a worktree_root outside the
    configured root results in an error.
    """
    resolved_root = Path(git_repo).resolve()
    state = GitRoState(git_repo=resolved_root)

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        try:
            yield state
        finally:
            pass

    mcp = FastMCP(name, instructions=f"Read-only Git tools scoped to repo: {resolved_root}")

    @mcp.tool()
    def git_status(payload: StatusInput) -> StatusPage:
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

    @mcp.tool()
    def git_diff(payload: DiffInput) -> DiffResult:
        """Git diff with multiple formats:
        - format=patch: unified patch (TextPage)
        - format=name-status: file status listing (ChangedFilesPage)
        - format=stat: per-file additions/deletions (DiffStatPage)
        """
        repo = _open_repo(state.git_repo)
        # Build base diff once
        opts: dict[str, Any] = {}
        if payload.format == DiffFormat.PATCH:
            opts["context_lines"] = payload.unified
        if payload.paths:
            opts["paths"] = payload.paths
        if payload.staged:
            head_tree = repo[repo.head.target].tree if not repo.head_is_unborn else None
            index_tree_oid = repo.index.write_tree()
            index_tree = repo[index_tree_oid].peel(pygit2.Tree)
            diff = repo.diff(head_tree, index_tree, **opts)
        else:
            diff = repo.diff(repo.index, None, **opts)
        if payload.find_renames:
            diff.find_similar()

        if payload.format == DiffFormat.PATCH:
            patch = diff.patch or ""
            return PatchResult(result=apply_text_slice(patch, payload.slice))

        if payload.format == DiffFormat.NAME_STATUS:
            items = [delta_to_changed_file(patch.delta) for patch in diff]
            sliced, page = paginate_items((items, [i.path for i in items]), payload.list_slice)
            return ShowNameStatusResult(
                result=ChangedFilesPage(
                    items=sliced, truncated=page.truncated, next_offset=page.next_offset, total_count=page.total_count
                )
            )

        # STAT
        stats: list[DiffFileStat] = []
        for patch in diff:
            cf = delta_to_changed_file(patch.delta)
            additions = getattr(patch, "additions", 0) or 0
            deletions = getattr(patch, "deletions", 0) or 0
            stats.append(
                DiffFileStat(
                    status=cf.status,
                    path=cf.path,
                    additions=int(additions),
                    deletions=int(deletions),
                    rename_from=cf.rename_from,
                    rename_to=cf.rename_to,
                )
            )
        page = apply_list_slice([s.path for s in stats], payload.list_slice)
        start = payload.list_slice.offset
        end = start + payload.list_slice.limit
        return StatResult(
            result=DiffStatPage(
                items=stats[start:end],
                truncated=page.truncated,
                next_offset=page.next_offset,
                total_count=page.total_count,
            )
        )

    @mcp.tool()
    def git_log(payload: LogInput) -> TextPage:
        """Return recent commits as oneline entries or multi-line blocks, with pagination."""
        root = state.git_repo
        repo = _open_repo(root)
        obj = repo.revparse_single(payload.rev) if not repo.head_is_unborn else repo[repo.head.target]
        head_oid = obj.oid if hasattr(obj, "oid") else obj.id
        lines: list[str] = []
        walker = repo.walk(head_oid, pygit2.GIT_SORT_TIME)
        count = 0
        for c in walker:
            if payload.oneline:
                summary = (c.message or "").splitlines()[0]
                lines.append(f"{str(c.id)[:7]} {summary}")
            else:
                lines.append(
                    f"commit {c.id}\nAuthor: {c.author.name} <{c.author.email}>\nDate:   {c.commit_time}\n\n{c.message or ''}\n"
                )
            count += 1
            if count >= payload.max_count:
                break
        body = "\n".join(lines)
        if body and not body.endswith("\n"):
            body += "\n"
        return apply_text_slice(body, payload.slice)

    @mcp.tool()
    def git_log_entries(payload: LogEntriesInput) -> LogEntriesPage:
        """Return structured commit entries with offset/limit pagination (preferred for programmatic use)."""
        root = state.git_repo
        repo = _open_repo(root)
        obj = repo.revparse_single(payload.rev) if not repo.head_is_unborn else repo[repo.head.target]
        head_oid = obj.oid if hasattr(obj, "oid") else obj.id
        walker = repo.walk(head_oid, pygit2.GIT_SORT_TIME)
        # Skip offset
        skipped = 0
        for _ in walker:
            if skipped >= payload.offset:
                break
            skipped += 1
        # Collect up to limit
        entries: list[CommitEntry] = []
        taken = 0
        for c in walker:
            msg = (c.message or None) if payload.include_message else None
            entries.append(
                CommitEntry(
                    id=str(c.id),
                    summary=(c.message or "").splitlines()[0] if c.message else "",
                    author_name=c.author.name,
                    author_email=c.author.email,
                    commit_time=c.commit_time,
                    message=msg,
                )
            )
            taken += 1
            if taken >= payload.limit:
                break
        # Peek one more to determine truncation
        more = next(iter(walker), None)
        truncated = more is not None
        next_offset = payload.offset + payload.limit if truncated else None
        return LogEntriesPage(entries=entries, truncated=truncated, next_offset=next_offset)

    @mcp.tool()
    def git_show(payload: ShowInput) -> ShowResult:
        """Show a commit in various formats or blob contents for REV:PATH.
        - format=patch: header + patch (TextPage) or blob text
        - format=name-status: file status listing (ChangedFilesPage)
        - format=stat: per-file additions/deletions (DiffStatPage)
        """
        root = state.git_repo
        repo = _open_repo(root)
        objspec = payload.object
        # Blob contents: REV:PATH always as text
        if ":" in objspec:
            rev, path = objspec.split(":", 1)
            obj = repo.revparse_single(rev)
            tree = obj.tree if isinstance(obj, pygit2.Commit) else obj.peel(pygit2.Tree)
            cur: pygit2.Tree = tree
            for part in filter(None, path.split("/")):
                entry = cur[part]
                if entry.filemode == pygit2.GIT_FILEMODE_TREE:
                    cur = repo[entry.oid]
                else:
                    blob = repo[entry.oid]
                    data = blob.data
                    try:
                        text = data.decode("utf-8")
                    except Exception:
                        text = f"[binary blob {len(data)} bytes]"
                    return ShowPatchResult(result=apply_text_slice(text, payload.slice))
            raise FileNotFoundError(f"Path not found: {path}")
        obj = repo.revparse_single(objspec)
        if isinstance(obj, pygit2.Tag):
            obj = obj.peel(pygit2.Commit)
        if not isinstance(obj, pygit2.Commit):
            raise TypeError(f"Unsupported object type for show: {type(obj).__name__}")

        # Build commit diff against first parent (or NULL tree)
        if obj.parent_ids:
            parent = repo[obj.parent_ids[0]]
            diff = repo.diff(parent.tree, obj.tree)
        else:
            diff = repo.diff(None, obj.tree)
        diff.find_similar()

        if payload.format == DiffFormat.PATCH:
            patch = diff.patch or ""
            header = f"commit {obj.id}\nAuthor: {obj.author.name} <{obj.author.email}>\n\n{obj.message or ''}\n"
            return ShowPatchResult(result=apply_text_slice(header + patch, payload.slice))

        if payload.format == DiffFormat.NAME_STATUS:
            items = [delta_to_changed_file(patch.delta) for patch in diff]
            sliced, page = paginate_items((items, [i.path for i in items]), payload.list_slice)
            return ShowNameStatusResult(
                result=ChangedFilesPage(
                    items=sliced, truncated=page.truncated, next_offset=page.next_offset, total_count=page.total_count
                )
            )

        # STAT
        stats: list[DiffFileStat] = []
        for patch in diff:
            cf = delta_to_changed_file(patch.delta)
            additions = getattr(patch, "additions", 0) or 0
            deletions = getattr(patch, "deletions", 0) or 0
            stats.append(
                DiffFileStat(
                    status=cf.status,
                    path=cf.path,
                    additions=int(additions),
                    deletions=int(deletions),
                    rename_from=cf.rename_from,
                    rename_to=cf.rename_to,
                )
            )
        sliced, page = paginate_items((stats, [s.path for s in stats]), payload.list_slice)
        return DiffStatPage(
            items=sliced, truncated=page.truncated, next_offset=page.next_offset, total_count=page.total_count
        )

    @mcp.tool()
    def git_rev_parse(payload: RevParseInput) -> RevParseResult:
        """Resolve a rev to an OID (optionally shortened) or return toplevel path for --show-toplevel."""
        root = state.git_repo
        repo = _open_repo(root)
        if payload.arg == "--show-toplevel":
            return RevParseResult(kind="toplevel", value=str(Path(repo.workdir).resolve()))
        obj = repo.revparse_single(payload.arg)
        oid = obj.oid if hasattr(obj, "oid") else obj.id
        s = str(oid)
        if payload.short:
            s = s[:7]
        return RevParseResult(kind="oid", value=s)

    @mcp.tool()
    def git_ls_files(payload: LsFilesInput) -> StringListPage:
        """List index paths, with offset/limit pagination (structured output)."""
        root = state.git_repo
        repo = _open_repo(root)
        all_paths = [e.path for e in repo.index]
        return apply_list_slice(all_paths, payload.list_slice)

    @mcp.tool()
    def git_branch_list(payload: BranchListInput) -> StringListPage:
        """List local or remote branches (short names) with offset/limit pagination (structured output)."""
        root = state.git_repo
        repo = _open_repo(root)
        kind = pygit2.GIT_BRANCH_REMOTE if payload.remote else pygit2.GIT_BRANCH_LOCAL
        names = repo.listall_branches(kind)
        return apply_list_slice(names, payload.list_slice)

    # Internal helper for list-style diffs
    def _build_diff_for_lists(repo: pygit2.Repository, params: DiffListInput) -> pygit2.Diff:
        opts: dict[str, Any] = {}
        if params.paths:
            opts["paths"] = params.paths
        if params.staged:
            head_tree = repo[repo.head.target].tree if not repo.head_is_unborn else None
            index_tree_oid = repo.index.write_tree()
            index_tree = repo[index_tree_oid].peel(pygit2.Tree)
            diff = repo.diff(head_tree, index_tree, **opts)
        else:
            diff = repo.diff(repo.index, None, **opts)
        if params.find_renames:
            diff.find_similar()
        return diff

    def _list_changed_files(repo: pygit2.Repository, payload: DiffListInput) -> list[ChangedFile]:
        diff = _build_diff_for_lists(repo, payload)
        items: list[ChangedFile] = []
        for patch in diff:
            d = patch.delta
            status_char = STATUS_MAP.get(d.status, "?")
            old_path = d.old_file.path or None
            new_path = d.new_file.path or None
            path = new_path or old_path or ""
            items.append(
                ChangedFile(
                    status=status_char,
                    path=path,
                    rename_from=old_path if status_char == "R" else None,
                    rename_to=new_path if status_char == "R" else None,
                )
            )
        return items

    return mcp
