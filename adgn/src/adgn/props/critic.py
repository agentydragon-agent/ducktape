"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via ``submit``.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call ``submit(issues_count)`` after building the critique using the incremental tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler
from adgn.agent.reducer import GateUntil
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import CRITIC_SUBMIT_SERVER_NAME
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Critique
from adgn.props.docker_env import properties_docker_spec
from adgn.props.ids import BaseIssueID, SpecimenSlug
from adgn.props.lint_issue import BootstrapInspectHandler
from adgn.props.models.issue import LineRange, Occurrence
from adgn.props.rationale import Rationale
from adgn.props.splits import Split, get_split

# Deferred import to avoid circular dependency (SpecimenRegistry imports from this module)
if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# File Scope Types and Constants
# =============================================================================

ALL_FILES_WITH_ISSUES: Literal["all"] = "all"
"""Sentinel value: scope critic to all files with ground truth TP/FP issues."""

type FileScopeSpec = set[Path] | Literal["all"]
"""File scope specification - either explicit file set or ALL_FILES_WITH_ISSUES sentinel.
Requires resolution via resolve_critic_scope() to produce ResolvedFileScope."""

type ResolvedFileScope = set[Path]
"""Resolved file scope - guaranteed to be an explicit set of paths (no sentinels)."""


# =============================================================================
# Critic Scope and Run Models
# =============================================================================


class CriticInput(BaseModel):
    """Input for a critic run (codebase → candidate issues).

    Files can be specified as:
    - ALL_FILES_WITH_ISSUES sentinel: resolved to files with ground truth TP/FP issues
    - Explicit set[Path]: specific files to review

    Resolution happens inside run_critic().
    """

    specimen_slug: SpecimenSlug = Field(description="Specimen slug (e.g., ducktape/2025-11-26-00)")
    files: FileScopeSpec = Field(
        description=f'Files to review: explicit set or "{ALL_FILES_WITH_ISSUES}" sentinel for ground truth files'
    )
    prompt_sha256: str = Field(description="SHA256 hash of the system prompt for reproducibility tracking")
    prompt_optimization_run_id: UUID | None = Field(
        default=None, description="Optional link to prompt optimization session"
    )

    model_config = ConfigDict(extra="forbid")

    @property
    def split(self) -> Split:
        """Compute split from specimen membership."""
        return get_split(self.specimen_slug)


class CriticSuccess(BaseModel):
    """Successful critic output."""

    tag: Literal["success"] = "success"
    result: CriticSubmitPayload = Field(description="Successful critique with issues and optional notes")

    model_config = ConfigDict(frozen=True)


class CriticFailure(BaseModel):
    """Failed critic output."""

    tag: Literal["failure"] = "failure"
    error: str = Field(description="Error message explaining why critique failed")

    model_config = ConfigDict(frozen=True)


# Discriminated union for critic output
CriticOutput = Annotated[CriticSuccess | CriticFailure, Field(discriminator="tag")]


# =============================================================================
# Critic Submit Models
# =============================================================================


class ReportedIssue(BaseModel):
    """Candidate issue reported by the critic (flattened header).

    Exposes only id and rationale; internal-only fields like should_flag are not part of the critic schema.

    Note: occurrences may be empty while the critique is being built incrementally; the submit tool enforces ≥1.
    """

    id: BaseIssueID
    rationale: Rationale
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


@dataclass
class CriticSubmitState:
    """Container for submitted CriticSubmitPayload or an error."""

    result: CriticSubmitPayload | None = None
    error: str | None = None
    # In-progress incremental payload (used by upsert/add_* tools before submit)
    work: CriticSubmitPayload = field(default_factory=CriticSubmitPayload)


class SubmitAck(BaseModel):
    ok: bool = Field(default=True, description="Submit succeeded")
    issues: int = Field(description="Number of issues submitted")
    occurrences: int = Field(description="Total number of occurrences submitted")

    model_config = ConfigDict(extra="forbid")


class ReportFailureInput(BaseModel):
    """Input for report_failure tool."""

    message: str = Field(description="Error message explaining why critique could not be completed")

    model_config = ConfigDict(extra="forbid")


def _find_this_critique(work: CriticSubmitPayload, issue_id: BaseIssueID) -> tuple[int, ReportedIssue] | None:
    """Find an issue by ID in the work payload.

    Returns:
        Tuple of (index, issue) if found, None otherwise.
    """
    for idx, issue in enumerate(work.issues):
        if issue.id == issue_id:
            return idx, issue
    return None


def _ensure_not_submitted(state: CriticSubmitState) -> None:
    """Raise ToolError if critique has already been submitted."""
    if (state.result is not None) or (state.error is not None):
        raise ToolError("Critique has already been submitted for this run.")


# --- Incremental tool input models (module-scope to avoid ForwardRef issues) ---
RangeAtom = int | list[int]


class UpsertIssueInput(BaseModel):
    """Create or update an issue header (id + rationale)."""

    issue_id: BaseIssueID
    description: str = Field(description="Issue rationale/description")

    model_config = ConfigDict(extra="forbid")


class CancelIssueInput(BaseModel):
    """Remove an issue and all its occurrences by id."""

    issue_id: BaseIssueID

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceInput(BaseModel):
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """

    issue_id: BaseIssueID
    file: Annotated[str, StringConstraints(pattern=r"^[^\n]+$")]
    ranges: Annotated[
        list[RangeAtom], Field(min_length=1, description="List of single lines (int) or spans [start,end]")
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

    issue_id: BaseIssueID
    files: dict[Annotated[str, StringConstraints(pattern=r"^[^\n]+$")], list[RangeAtom]]

    model_config = ConfigDict(extra="forbid")


CRITIC_MCP_INSTRUCTIONS = (
    "Critique builder: incrementally add issues and occurrences, then call submit(issues) when complete.\n\n"
    "For multiple occurrences of the same issue, call add_occurrence repeatedly.\n"
    "For a single occurrence spanning multiple files/ranges, use add_occurrence_files.\n"
)


def build_critic_submit_tools(mcp: NotifyingFastMCP, state: CriticSubmitState) -> None:
    """Register critic submit tools on the provided server (tools-builder pattern)."""

    def _parse_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
        def _parse_range_atom(a: RangeAtom) -> LineRange:
            if isinstance(a, int):
                return LineRange(start_line=a)
            if isinstance(a, list) and len(a) == 2 and all(isinstance(x, int) for x in a):
                return LineRange(start_line=a[0], end_line=a[1])
            raise ValueError(f"Invalid range atom: {a!r}. Expected int or [start, end]")

        return [_parse_range_atom(a) for a in atoms]

    @mcp.flat_model()
    async def upsert_issue(payload: UpsertIssueInput) -> str:
        """Create or update an issue header (id + rationale)."""
        result = _find_this_critique(state.work, payload.issue_id)
        if result is not None:
            idx, existing = result
            state.work.issues[idx] = ReportedIssue(
                id=payload.issue_id, rationale=payload.description, occurrences=existing.occurrences
            )
        else:
            state.work.issues.append(ReportedIssue(id=payload.issue_id, rationale=payload.description, occurrences=[]))
        return f"issue {payload.issue_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence"

    @mcp.flat_model()
    async def cancel_issue(payload: CancelIssueInput) -> str:
        """Remove an issue and all its occurrences by id."""
        state.work.issues = [it for it in state.work.issues if it.id != payload.issue_id]
        after_issues = len(state.work.issues)
        after_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"issue {payload.issue_id} canceled. {after_issues} issues ({after_occs} occurrences) noted."

    @mcp.flat_model()
    async def add_occurrence(payload: AddOccurrenceInput) -> str:
        """Add one occurrence for an issue."""
        result = _find_this_critique(state.work, payload.issue_id)
        if result is None:
            raise ToolError(f"Unknown issue '{payload.issue_id}'. Create the issue before adding occurrences.")
        issue = result[1]
        issue.occurrences.append(Occurrence(files={Path(payload.file): _parse_ranges(payload.ranges)}))
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted."

    @mcp.tool()
    async def show_critique() -> CriticSubmitPayload:
        return state.work

    @mcp.flat_model()
    async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> str:
        """Add one occurrence spanning multiple files/ranges."""
        result = _find_this_critique(state.work, payload.issue_id)
        if result is None:
            raise ToolError(f"Unknown issue '{payload.issue_id}'. Create the issue before adding occurrences.")
        issue = result[1]
        issue.occurrences.append(
            Occurrence(files={Path(p): _parse_ranges(r) for p, r in (payload.files or {}).items()})
        )
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"multi-file occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted."

    @mcp.flat_model()
    async def submit(payload: SubmitInput) -> SubmitAck:
        """Finalize critique (enforces count and at least one occurrence per issue)."""
        _ensure_not_submitted(state)
        missing = [it.id for it in state.work.issues if not it.occurrences]
        if missing:
            raise ToolError(
                "Each issue must include at least one occurrence. Missing occurrences for: "
                + ", ".join(str(x) for x in missing)
            )
        actual_issues = len(state.work.issues)
        if payload.issues != actual_issues:
            raise ToolError(f"Submit count mismatch: reported {payload.issues} but found {actual_issues}.")
        state.result = state.work
        occs = sum(len(i.occurrences) for i in state.work.issues)
        return SubmitAck(issues=actual_issues, occurrences=occs)

    @mcp.flat_model()
    async def report_failure(error: ReportFailureInput) -> str:
        """Report that critique could not be completed."""
        _ensure_not_submitted(state)
        state.error = error.message
        raise ToolError(error.message)


def _format_file_ranges(path: Path, ranges: list[LineRange] | None) -> str:
    """Format a file path with its line ranges (e.g., 'file.py: 123, 145-150')."""
    if ranges is None:
        return f"{path}: (unspecified)"
    return f"{path}: {', '.join(r.format() for r in ranges)}"


def _format_occurrence(occ: Occurrence) -> str:
    """Format a single occurrence (multiple files with optional note)."""
    files = [_format_file_ranges(p, ranges) for p, ranges in (occ.files or {}).items()]
    result = "; ".join(files)
    if occ.note:
        result += f" ({occ.note})"
    return result


def _format_occurrences(issue: ReportedIssue) -> str:
    """Format all occurrences for an issue as a newline-separated string."""
    return "\n".join(_format_occurrence(occ) for occ in issue.occurrences)


@render_to_rich.register
def _render_critic_submit_payload(obj: CriticSubmitPayload):
    bits: list[RenderableType] = []
    # Candidate issues table (no properties column)
    tbl = Table(title="Candidate Issues", show_lines=False, expand=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Rationale", style="green")
    tbl.add_column("Occurrences", style="yellow")

    if obj.issues:
        for issue in obj.issues:
            tbl.add_row(issue.id, issue.rationale, _format_occurrences(issue))
    else:
        tbl.add_row("(no candidate issues)", "", "")

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


# =============================================================================
# Critic Scope Resolution
# =============================================================================


async def resolve_critic_scope(specimen_slug: SpecimenSlug, files: FileScopeSpec) -> ResolvedFileScope:
    """Resolve file scope for critic, handling ALL_FILES_WITH_ISSUES sentinel.

    Args:
        specimen_slug: Target specimen
        files: Explicit file set or ALL_FILES_WITH_ISSUES sentinel

    Returns:
        Resolved file set (guaranteed non-empty)

    Raises:
        ValueError: If sentinel is used but specimen has no files with issues
    """
    # Import here to avoid circular dependency at module load time
    from adgn.props.specimens.registry import SpecimenRegistry

    if files == ALL_FILES_WITH_ISSUES:
        async with SpecimenRegistry.load_and_hydrate(specimen_slug) as hydrated:
            resolved_files = hydrated.files_with_issues()
            if not resolved_files:
                raise ValueError(
                    f"Specimen '{specimen_slug}' has no files with ground truth issues. "
                    f"Cannot use '{ALL_FILES_WITH_ISSUES}' sentinel."
                )
    else:
        resolved_files = files

    return resolved_files


# =============================================================================
# Critic Run Function
# =============================================================================


async def run_critic(
    *,
    input_data: CriticInput,
    client: OpenAIModelProto,
    system_prompt: str,
    user_prompt: str,
    content_root,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
) -> tuple[CriticSuccess, UUID, UUID]:
    """Execute critic agent to produce candidate issues and persist to DB.

    Sets up critic submit server, Docker exec MCP, and standard handlers (bootstrap,
    database events, GateUntil). Runs agent until submit_result or error is called.

    Returns tuple of (output, critic_run_id, critique_id). Raises RuntimeError on failure.
    Note: Returns IDs only (not ORM objects) to avoid DetachedInstanceError when called
    from within an MCP tool that outlives the session.
    """
    # Resolve file scope (handles ALL_FILES_WITH_ISSUES sentinel)
    resolved_files = await resolve_critic_scope(input_data.specimen_slug, input_data.files)

    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        db_run = DBCriticRun(
            id=run_id,
            transcript_id=transcript_id,
            prompt_sha256=input_data.prompt_sha256,
            specimen_slug=input_data.specimen_slug,
            model=client.model,
            critique_id=None,  # Will be set in Phase 2 if successful
            prompt_optimization_run_id=input_data.prompt_optimization_run_id,
            files=sorted(str(p) for p in resolved_files),
            output=None,  # Will be set in Phase 2
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial critic run in DB: {run_id=}, {transcript_id=}, specimen_slug={input_data.specimen_slug}"
        )

    # Set up critic submit server and state
    critic_state = CriticSubmitState()
    wiring = properties_docker_spec(content_root, mount_properties=mount_properties)
    comp = Compositor("compositor")
    runtime_server = await wiring.attach(comp)

    # Mount critic submit server
    critic_server = NotifyingFastMCP(CRITIC_SUBMIT_SERVER_NAME, instructions=CRITIC_MCP_INSTRUCTIONS)
    build_critic_submit_tools(critic_server, critic_state)
    await comp.mount_inproc(CRITIC_SUBMIT_SERVER_NAME, critic_server)

    # Set up handlers
    bootstrap = BootstrapInspectHandler(wiring)

    # Build servers dict for handlers
    servers = {wiring.server_name: runtime_server, CRITIC_SUBMIT_SERVER_NAME: critic_server}

    def _ready_state() -> bool:
        return (critic_state.result is not None) or (critic_state.error is not None)

    handlers: list = [
        bootstrap,
        *build_props_handlers(
            transcript_id=transcript_id,
            verbose_prefix=f"[CRITIC {input_data.specimen_slug}] " if verbose else None,
            servers=servers,
        ),
        GateUntil(_ready_state, defer_when=lambda: not bootstrap._done),
        *extra_handlers,
    ]

    # Run critic agent
    async with Client(comp) as mcp_client:
        await mount_standard_inproc_servers(compositor=comp)
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            system=system_prompt,
            client=client,
            handlers=handlers,
            parallel_tool_calls=True,
            reasoning_summary=ReasoningSummary.detailed,
        )
        await agent.run(user_prompt)

    # Convert state to output
    if critic_state.error is not None:
        raise RuntimeError(f"Critic failed: {critic_state.error}")
    if critic_state.result is None:
        raise RuntimeError("Critic did not submit")

    output = CriticSuccess(result=critic_state.result)

    # Phase 2: Update run with output
    with get_session() as session:
        # Create critique if successful
        critique_id = None
        if isinstance(output, CriticSuccess):
            critique = Critique(specimen_slug=input_data.specimen_slug, payload=output.result.model_dump(mode="json"))
            session.add(critique)
            session.flush()
            critique_id = critique.id

        # Update run with output and critique_id
        found_run = session.get(DBCriticRun, run_id)
        assert found_run is not None, f"Critic run {run_id} not found in database"
        found_run.output = output.model_dump(mode="json")
        found_run.critique_id = critique_id
        session.commit()

        # Extract IDs before session closes (never return ORM objects from functions)
        result_id = found_run.id
        result_critique_id = found_run.critique_id
        logger.info(f"Updated critic run in DB: {transcript_id=}, specimen_slug={input_data.specimen_slug}")

    # Return plain IDs, not ORM objects (SQLAlchemy best practice: never return ORM objects from
    # functions that manage their own sessions - they become detached and cause errors)
    return (output, result_id, result_critique_id)
