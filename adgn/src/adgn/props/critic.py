"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via ``submit``.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call ``submit(issues_count)`` after building the critique using the incremental tools.
"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import CRITIC_SUBMIT_SERVER_NAME
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.props.models.issue import IssueId, LineRange, Occurrence


class ReportedIssue(BaseModel):
    """Candidate issue reported by the critic (flattened header).

    Exposes only id and rationale; internal-only fields like should_flag/gap_note are not part of the critic schema.

    Note: occurrences may be empty while the critique is being built incrementally; the submit tool enforces ≥1.
    """

    id: IssueId
    rationale: str
    occurrences: list[Occurrence] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CriticSubmitPayload(BaseModel):
    """Structured critic output."""

    issues: list[ReportedIssue] = Field(default_factory=list, description="Issues found")
    notes_md: str | None = Field(
        default=None,
        description="Optional Markdown note. Only for info not represented in structured form in `issues`.",
    )
    model_config = ConfigDict(extra="forbid")


class CriticErrorPayload(BaseModel):
    """Structured error report from critic when it cannot produce findings."""

    message: str = Field(description="Human-readable error summary")
    model_config = ConfigDict(extra="forbid")


class CriticSubmitState:
    """Container for submitted CriticSubmitPayload or an error."""

    result: CriticSubmitPayload | None = None
    error: CriticErrorPayload | None = None
    # In-progress incremental payload (used by upsert/add_* tools before submit)
    work: CriticSubmitPayload | None = None


class ToolAck(BaseModel):
    ok: bool = Field(default=True, description="Operation succeeded")
    message: str | None = Field(default=None, description="Optional human-friendly note")

    model_config = ConfigDict(extra="forbid")


class SubmitAck(BaseModel):
    ok: bool = Field(default=True, description="Submit succeeded")
    issues: int = Field(description="Number of issues submitted")
    occurrences: int = Field(description="Total number of occurrences submitted")

    model_config = ConfigDict(extra="forbid")


def _raise_unknown_issue(issue_id: IssueId) -> NoReturn:
    """Raise a ToolError for unknown issue references (DRY helper)."""
    raise ToolError(f"Unknown issue '{issue_id}'. Create the issue before adding occurrences.")


def _raise_already_submitted() -> NoReturn:
    """Raise a ToolError when a critique has already been submitted for the run."""
    raise ToolError("Critique has already been submitted for this run.")


# --- Incremental tool input models (module-scope to avoid ForwardRef issues) ---
RangeAtom = int | list[int]


class UpsertIssueInput(BaseModel):
    """Create or update an issue header (id + rationale)."""

    issue_id: IssueId
    description: str = Field(description="Issue rationale/description")

    model_config = ConfigDict(extra="forbid")


class CancelIssueInput(BaseModel):
    """Remove an issue and all its occurrences by id."""

    issue_id: IssueId

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceInput(BaseModel):
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """

    issue_id: IssueId
    file: Annotated[str, StringConstraints(pattern=r"^[^\n]+$")]
    ranges: Annotated[
        list[RangeAtom], Field(min_items=1, description="List of single lines (int) or spans [start,end]")
    ]

    model_config = ConfigDict(extra="forbid")


class SubmitInput(BaseModel):
    """Finalize: the model must state the number of issues it believes it created."""

    issues: int = Field(ge=0, description="Count of issues in the critique at submit time")

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceFilesInput(BaseModel):
    """Add one occurrence spanning multiple files and ranges.

    files: map of file -> list of range atoms (int or [start,end]).
    """

    issue_id: IssueId
    files: dict[Annotated[str, StringConstraints(pattern=r"^[^\n]+$")], list[RangeAtom]]

    model_config = ConfigDict(extra="forbid")


CRITIC_MCP_INSTRUCTIONS = (
    "Critique builder: incrementally add issues and occurrences, then call submit(issues) when complete.\n\n"
    "Notes:\n"
    "- Tools are self-describing via MCP; consult tool schemas instead of this banner.\n"
    "- For multiple occurrences of the same issue, call add_occurrence repeatedly.\n"
    "- For a single occurrence spanning multiple files/ranges, use add_occurrence_files.\n"
)


def build_critic_submit_tools(mcp: NotifyingFastMCP, state: CriticSubmitState) -> None:
    """Register critic submit tools on the provided server (tools-builder pattern)."""

    def _ensure_work_payload() -> CriticSubmitPayload:
        work = state.work
        if work is None:
            work = CriticSubmitPayload()
            state.work = work
        return work

    def _normalize_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
        out: list[LineRange] = []
        for a in atoms:
            if isinstance(a, int):
                out.append(LineRange(start_line=int(a)))
            elif isinstance(a, list) and len(a) == 2 and all(isinstance(x, int) for x in a):
                start, end = int(a[0]), int(a[1])
                out.append(LineRange(start_line=start, end_line=end))
            else:
                raise ValueError("ranges items must be int or [start,end]")
        return out

    @mcp.flat_model()
    async def upsert_issue(payload: UpsertIssueInput) -> ToolAck:
        """Create or update an issue header (id + rationale)."""
        work = _ensure_work_payload()
        for idx, it in enumerate(work.issues):
            if it.id == payload.issue_id:
                work.issues[idx] = ReportedIssue(
                    id=payload.issue_id, rationale=payload.description, occurrences=it.occurrences
                )
                break
        else:
            work.issues.append(ReportedIssue(id=payload.issue_id, rationale=payload.description, occurrences=[]))
        return ToolAck(
            message=f"issue {payload.issue_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence"
        )

    @mcp.flat_model()
    async def cancel_issue(payload: CancelIssueInput) -> ToolAck:
        """Remove an issue and all its occurrences by id."""
        work = _ensure_work_payload()
        work.issues = [it for it in work.issues if it.id != payload.issue_id]
        after_issues = len(work.issues)
        after_occs = sum(len(i.occurrences) for i in work.issues)
        return ToolAck(
            message=f"issue {payload.issue_id} canceled. {after_issues} issues ({after_occs} occurrences) noted."
        )

    @mcp.flat_model()
    async def add_occurrence(payload: AddOccurrenceInput) -> ToolAck:
        """Add one occurrence for an issue."""
        work = _ensure_work_payload()
        for it in work.issues:
            if it.id == payload.issue_id:
                files_map: dict[str, list[LineRange] | None] = {payload.file: _normalize_ranges(payload.ranges)}
                it.occurrences.append(Occurrence(files=files_map))
                total_occs = sum(len(i.occurrences) for i in work.issues)
                return ToolAck(
                    message=f"occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted."
                )
        _raise_unknown_issue(payload.issue_id)

    @mcp.tool()
    async def show_critique() -> CriticSubmitPayload:
        return _ensure_work_payload()

    @mcp.flat_model()
    async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> ToolAck:
        """Add one occurrence spanning multiple files/ranges."""
        work = _ensure_work_payload()
        for it in work.issues:
            if it.id == payload.issue_id:
                files_map: dict[str, list[LineRange] | None] = {
                    p: _normalize_ranges(r) for p, r in (payload.files or {}).items()
                }
                it.occurrences.append(Occurrence(files=files_map))
                total_occs = sum(len(i.occurrences) for i in work.issues)
                return ToolAck(
                    message=f"multi-file occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted."
                )
        _raise_unknown_issue(payload.issue_id)

    @mcp.flat_model()
    async def submit(payload: SubmitInput) -> SubmitAck:
        """Finalize critique (enforces count and at least one occurrence per issue)."""
        if (state.result is not None) or (state.error is not None):
            _raise_already_submitted()
        work = _ensure_work_payload()
        missing = [it.id for it in work.issues if not it.occurrences]
        if missing:
            raise ToolError(
                "Each issue must include at least one occurrence. Missing occurrences for: "
                + ", ".join(str(x) for x in missing)
            )
        actual_issues = len(work.issues)
        if payload.issues != actual_issues:
            raise ToolError(f"Submit count mismatch: reported {payload.issues} but found {actual_issues}.")
        state.result = work
        occs = sum(len(i.occurrences) for i in work.issues)
        return SubmitAck(issues=actual_issues, occurrences=occs)

    @mcp.flat_model()
    async def report_failure(error: CriticErrorPayload) -> ToolAck:
        """Report that critique could not be completed."""
        if (state.result is not None) or (state.error is not None):
            _raise_already_submitted()
        state.error = error
        raise ToolError(error.message)


def make_critic_submit_server(state: CriticSubmitState, *, name: str = CRITIC_SUBMIT_SERVER_NAME) -> NotifyingFastMCP:
    """Create a Critic MCP server with typed, flat tools (single source of truth).

    Agent builds a critique incrementally via tools and must call submit(issues)
    once to finalize. The payload is validated and stored in state.result.
    """

    mcp = NotifyingFastMCP(name, instructions=CRITIC_MCP_INSTRUCTIONS)
    # Register tools via the shared builder to keep a single implementation
    build_critic_submit_tools(mcp, state)
    return mcp


async def attach_critic_submit(comp: Compositor, state: CriticSubmitState) -> NotifyingFastMCP:
    """Create and mount the critic_submit server on the given Compositor.

    Returns the created server for callers that want to keep a reference.
    """
    # Build typed server and attach in-proc (no auth)
    server = make_critic_submit_server(state, name=CRITIC_SUBMIT_SERVER_NAME)
    await comp.mount_inproc(CRITIC_SUBMIT_SERVER_NAME, server)
    return server


@render_to_rich.register
def _render_critic_submit_payload(obj: CriticSubmitPayload):
    bits: list[RenderableType] = []
    # Candidate issues table (no properties column)
    tbl = Table(title="Candidate Issues", show_lines=False, expand=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Rationale", style="green")
    tbl.add_column("Occurrences", style="yellow")

    if obj.issues:
        for ci in obj.issues:
            cid = ci.id or "(no id)"
            rationale = ci.rationale or ""
            occs = []
            for occ in ci.occurrences:
                files = []
                for p, ranges in (occ.files or {}).items():
                    if ranges is None:
                        files.append(f"{p}: (unspecified)")
                    else:
                        spans = ", ".join(
                            f"{r.start_line}" + (f"-{r.end_line}" if r.end_line is not None else "") for r in ranges
                        )
                        files.append(f"{p}: {spans}")
                note = f" ({occ.note})" if occ.note else ""
                occs.append("; ".join(files) + note)
            occs_text = "\n".join(occs)
            tbl.add_row(cid, rationale, occs_text)
    else:
        tbl.add_row("(no candidate issues)", "", "", "")

    bits.append(tbl)
    if obj.notes_md:
        bits.append(Markdown(obj.notes_md))

    if len(bits) == 1:
        body: RenderableType = bits[0]
    else:
        # simple group rendering for multiple blocks
        body = Group(*bits)

    title = f"Critic result ({len(obj.issues)} issues)"
    border = "red" if obj.issues else "green"
    return Panel(body, title=title, border_style=border)


@render_to_rich.register
def _render_critic_error_payload(obj: CriticErrorPayload):
    return Panel(Markdown(obj.message), title="Critic error", border_style="red")
