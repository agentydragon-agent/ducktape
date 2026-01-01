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
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

# FastMCP-only: no TokenVerifier in server construction
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, Field
import pygit2
from pygit2.enums import BranchType

from mcp_infra.enhanced.server import EnhancedFastMCP
from mcp_infra.prefix import MCPMountPrefix
from openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel

from .formatting import (
    ChangedFilesPage,
    DiffStatPage,
    ListSlice,
    StatusEntry,
    StatusPage,
    StringListPage,
    TextPage,
    TextSlice,
    apply_list_slice,
    apply_text_slice,
    build_changed_files_page,
    build_diff_stat_page,
    build_status_page,
    diff_to_changed_files,
    diff_to_file_stats,
)

# Shared mount prefix constant for clients/tests
GIT_RO_MOUNT_PREFIX = MCPMountPrefix("git_ro")

# -------------------------- shared slicing -----------------------------------


## moved to formatting.py


# -------------------------- helpers -----------------------------------------


def get_oid(obj: Any):
    """Return object id (pygit2 >=1.18 provides .id consistently)."""
    return obj.id


# -------------------------- inputs ------------------------------------------


class StatusInput(OpenAIStrictModeBaseModel):
    """Input model for git_status with optional pagination."""

    list_slice: ListSlice


class DiffFormat(StrEnum):
    PATCH = "patch"
    NAME_STATUS = "name-status"
    STAT = "stat"


class DiffInput(OpenAIStrictModeBaseModel):
    format: DiffFormat
    staged: bool = Field(description="If true, diff --cached (staged changes)")
    unified: int = Field(
        ge=0, le=1000, description="Context lines (-U<N>) for patch format (0..1000; 0 shows only headers/hunks)"
    )
    rev_a: str | None = Field(description="Left side rev for range diff (e.g., HEAD^)")
    rev_b: str | None = Field(description="Right side rev for range diff (e.g., HEAD)")
    paths: list[str] | None = Field(description="Optional pathspecs to limit diff")
    find_renames: bool = Field(description="Detect renames (-M)")
    slice: TextSlice
    list_slice: ListSlice


class LogInput(OpenAIStrictModeBaseModel):
    rev: str = Field(description="Revision or range (e.g., HEAD, HEAD~10..HEAD)")
    max_count: int = Field(description="Maximum number of entries")
    oneline: bool = Field(description="Format each commit as one line")
    slice: TextSlice


class ShowInput(OpenAIStrictModeBaseModel):
    object: str = Field(description="Object spec, e.g., HEAD, <sha>, or REV:PATH for blob content")
    format: DiffFormat
    slice: TextSlice
    list_slice: ListSlice


class RevParseInput(OpenAIStrictModeBaseModel):
    arg: str = Field(description="Argument to rev-parse (e.g., HEAD, --show-toplevel)")
    short: bool = Field(description="If true, shorten OIDs")


## moved to formatting.py


class RevParseResult(BaseModel):
    kind: Literal["oid", "toplevel"]
    value: str | Path


class LsFilesInput(OpenAIStrictModeBaseModel):
    cached: bool = Field(description="List index entries (same as non-cached here); kept for parity")
    list_slice: ListSlice


class BranchListInput(OpenAIStrictModeBaseModel):
    remote: bool = Field(description="List remote branches instead of local")
    list_slice: ListSlice


# Structured diff listing inputs/outputs
class DiffListInput(OpenAIStrictModeBaseModel):
    staged: bool = Field(description="If true, examine staged (index) changes; else worktree")
    paths: list[str] | None = Field(description="Optional pathspecs to limit the diff")
    find_renames: bool = Field(description="Detect renames (diff.find_similar)")
    list_slice: ListSlice


## moved to formatting.py


class LogEntriesInput(OpenAIStrictModeBaseModel):
    rev: str = Field(description="Revision to start from (e.g., HEAD)")
    offset: int = Field(ge=0, description="Number of commits to skip (pagination offset)")
    limit: int = Field(gt=0, le=1000, description="Max commits to return")
    include_message: bool = Field(description="Include full commit message body")


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
# For git_diff we return the complete page models directly
DiffResult = TextPage | ChangedFilesPage | DiffStatPage


# For git_show we also return the underlying page models directly
ShowResult = TextPage | ChangedFilesPage | DiffStatPage

# -------------------------- outputs -----------------------------------------

## Status enums removed - now using raw pygit2 flags (int) for type safety
## moved to formatting.py


# -------------------------- server ------------------------------------------


class GitRoServer(EnhancedFastMCP):
    """Git read-only MCP server with typed tool access.

    Subclasses EnhancedFastMCP and adds typed tool attributes for accessing
    tool names. This is the single source of truth - no string literals elsewhere.
    """

    # Tool references (assigned in __init__ after tool registration)
    status_tool: FunctionTool
    diff_tool: FunctionTool
    log_tool: FunctionTool
    show_tool: FunctionTool
    log_entries_tool: FunctionTool
    rev_parse_tool: FunctionTool
    ls_files_tool: FunctionTool
    branch_list_tool: FunctionTool

    def __init__(self, repo: pygit2.Repository):
        """Create a read-only Git FastMCP server for an already-opened repository."""
        state = repo
        repo_name = Path(repo.workdir or repo.path).name
        display = f"Git Read-Only MCP Server: {repo_name}"
        super().__init__(display, instructions=f"Read-only Git tools scoped to repo: {repo_name}")

        # Register tools using clean pattern: tool name derived from function name
        def status(input: StatusInput) -> StatusPage:
            """Return status entries with raw pygit2 flags for type-safe interpretation."""
            st = state.status()
            entries: list[StatusEntry] = []
            for path, flags in st.items():
                # Store raw pygit2 status flags for consumers to interpret
                entries.append(StatusEntry(path=Path(path), index=flags, worktree=flags))
            return build_status_page(entries, input.list_slice)

        self.status_tool = self.flat_model()(status)

        async def diff(input: DiffInput) -> DiffResult:
            """Git diff with multiple formats:
            - format=patch: unified patch (TextPage)
            - format=name-status: file status listing (ChangedFilesPage)
            - format=stat: per-file additions/deletions (DiffStatPage)
            """
            # Build base diff using repository-level APIs that match type stubs
            # Note: pygit2 stubs do not expose 'paths' filtering; filter results downstream if needed.
            a = None if state.head_is_unborn else state.head.target
            diff = state.diff(a, None, cached=input.staged)

            if input.find_renames:
                diff.find_similar()

            if input.format == DiffFormat.PATCH:
                patch_text = await asyncio.to_thread(lambda: diff.patch or "")
                return apply_text_slice(patch_text, input.slice)
            if input.format == DiffFormat.NAME_STATUS:
                items = await asyncio.to_thread(diff_to_changed_files, diff)
                return build_changed_files_page(items, input.list_slice)
            # STAT
            stats = await asyncio.to_thread(diff_to_file_stats, diff)
            return build_diff_stat_page(stats, input.list_slice)

        self.diff_tool = self.flat_model()(diff)

        def log(input: LogInput) -> TextPage:
            """Return recent commits as oneline entries or multi-line blocks, with pagination."""
            if state.head_is_unborn:
                return apply_text_slice("", input.slice)
            obj = state.revparse_single(input.rev)
            head_oid = get_oid(obj)
            lines: list[str] = []
            walker = state.walk(head_oid)
            for i, c in enumerate(walker, start=1):
                if input.oneline:
                    raw_message = (c.message or "").rstrip("\n")
                    prefix = str(c.id)[:7]
                    lines.append(f"{prefix} {raw_message}" if raw_message else prefix)
                else:
                    lines.append(
                        f"commit {c.id}\nAuthor: {c.author.name} <{c.author.email}>\nDate:   {c.commit_time}\n\n{c.message or ''}\n"
                    )
                if i >= input.max_count:
                    break
            body = "\n".join(lines)
            if body and not body.endswith("\n"):
                body += "\n"
            return apply_text_slice(body, input.slice)

        self.log_tool = self.flat_model()(log)

        def log_entries(input: LogEntriesInput) -> LogEntriesPage:
            """Return structured commit entries with offset/limit pagination (preferred for programmatic use)."""
            if state.head_is_unborn:
                return LogEntriesPage(entries=[], truncated=False, next_offset=None)
            obj = state.revparse_single(input.rev)
            head_oid = get_oid(obj)
            walker = state.walk(head_oid)
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
                    )
                )
                if i >= input.limit:
                    break
            # Peek one more to determine truncation
            more = next(iter(walker), None)
            truncated = more is not None
            next_offset = input.offset + input.limit if truncated else None
            return LogEntriesPage(entries=entries, truncated=truncated, next_offset=next_offset)

        self.log_entries_tool = self.flat_model()(log_entries)

        async def show(input: ShowInput) -> ShowResult:
            """Show a commit in various formats or blob contents for REV:PATH.
            - format=patch: header + patch (TextPage) or blob text
            - format=name-status: file status listing (ChangedFilesPage)
            - format=stat: per-file additions/deletions (DiffStatPage)
            """
            objspec = input.object
            # Blob contents: REV:PATH always as text
            if ":" in objspec:
                rev, path = objspec.split(":", 1)
                root_obj = state.revparse_single(rev)
                tree = root_obj.tree if isinstance(root_obj, pygit2.Commit) else root_obj.peel(pygit2.Tree)
                cur: pygit2.Tree = tree
                for part in filter(None, path.split("/")):
                    entry = cur[part]
                    if entry.filemode == pygit2.GIT_FILEMODE_TREE:
                        cur = state[entry.id].peel(pygit2.Tree)
                    else:
                        blob = state[entry.id].peel(pygit2.Blob)
                        data = blob.data
                        try:
                            text = data.decode("utf-8")
                        except UnicodeDecodeError:
                            text = f"[binary blob {len(data)} bytes]"
                        return apply_text_slice(text, input.slice)
                raise FileNotFoundError(f"Path not found: {path}")
            obj_any = state.revparse_single(objspec)
            # Narrow runtime types explicitly
            if isinstance(obj_any, pygit2.Tag):
                obj = obj_any.peel(pygit2.Commit)
            elif isinstance(obj_any, pygit2.Commit):
                obj = obj_any
            else:
                raise TypeError(f"Unexpected git object type for {objspec}: {type(obj_any)!r}")

            # Build commit diff against first parent (or empty tree)
            if obj.parents:
                parent = obj.parents[0]
                diff = state.diff(parent, obj)
            else:
                diff = state.diff(None, obj)
            diff.find_similar()

            if input.format == DiffFormat.PATCH:
                patch_text = await asyncio.to_thread(lambda: diff.patch or "")
                return apply_text_slice(patch_text, input.slice)

            if input.format == DiffFormat.NAME_STATUS:
                items = await asyncio.to_thread(diff_to_changed_files, diff)
                return build_changed_files_page(items, input.list_slice)

            # STAT
            stats = await asyncio.to_thread(diff_to_file_stats, diff)
            return build_diff_stat_page(stats, input.list_slice)

        self.show_tool = self.flat_model()(show)

        def rev_parse(input: RevParseInput) -> RevParseResult:
            """Resolve a rev to an OID (optionally shortened) or return toplevel path for --show-toplevel."""
            if input.arg == "--show-toplevel":
                workdir = state.workdir
                if not workdir:
                    raise ValueError("Repository has no working directory")
                return RevParseResult(kind="toplevel", value=Path(workdir).resolve())
            obj = state.revparse_single(input.arg)
            oid = get_oid(obj)
            s = str(oid)
            if input.short:
                s = s[:7]
            return RevParseResult(kind="oid", value=s)

        self.rev_parse_tool = self.flat_model()(rev_parse)

        def ls_files(input: LsFilesInput) -> StringListPage:
            """List index paths, with offset/limit pagination (structured output)."""
            all_paths = [e.path for e in state.index]
            items, truncated, next_offset, total = apply_list_slice(all_paths, input.list_slice)
            return StringListPage(items=items, truncated=truncated, next_offset=next_offset, total_items=total)

        self.ls_files_tool = self.flat_model()(ls_files)

        def branch_list(input: BranchListInput) -> StringListPage:
            """List local or remote branches (short names) with offset/limit pagination."""
            kind = BranchType.REMOTE if input.remote else BranchType.LOCAL
            names = state.listall_branches(kind)
            items, truncated, next_offset, total = apply_list_slice(names, input.list_slice)
            return StringListPage(items=items, truncated=truncated, next_offset=next_offset, total_items=total)

        self.branch_list_tool = self.flat_model()(branch_list)
