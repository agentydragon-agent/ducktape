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
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.agent.agent import MiniCodex
from adgn.agent.bootstrap import TypedBootstrapBuilder
from adgn.agent.handler import BaseHandler, SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.agent.reducer import AbortIf
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import CRITIC_SUBMIT_SERVER_NAME
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.critic.models import (
    ALL_FILES_WITH_ISSUES,
    CriticInput,
    CriticSubmitPayload,
    CriticSuccess,
    FileScopeSpec,
    ReportedIssue,
    ResolvedFileScope,
)
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Critique, Prompt
from adgn.props.docker_env import properties_docker_spec
from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.lint_issue import make_bootstrap_calls_for_inspection
from adgn.props.models.true_positive import LineRange, Occurrence
from adgn.props.prompts.util import render_prompt_template
from adgn.props.snapshot_registry import SnapshotRegistry

logger = logging.getLogger(__name__)


# =============================================================================
# Internal State and Tool Models
# =============================================================================


@dataclass
class CriticSubmitState:
    """Container for submitted CriticSubmitPayload or an error."""

    result: CriticSubmitPayload | None = None
    error: str | None = None
    # In-progress incremental payload (used by upsert/add_* tools before submit)
    work: CriticSubmitPayload = field(default_factory=CriticSubmitPayload)


class CriticFailure(BaseModel):
    """Failed critic output (not used in current API but kept for potential future use)."""

    tag: Literal["failure"] = "failure"
    error: str = Field(description="Error message explaining why critique failed")

    model_config = ConfigDict(frozen=True)


# Discriminated union for critic output (not currently used but defined for completeness)
CriticOutput = Annotated[CriticSuccess | CriticFailure, Field(discriminator="tag")]


class ReportFailureInput(BaseModel):
    """Input for report_failure tool."""

    message: str = Field(description="Error message explaining why critique could not be completed")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Internal Helper Functions
# =============================================================================


def _find_this_critique(work: CriticSubmitPayload, tp_id: BaseIssueID) -> tuple[int, ReportedIssue] | None:
    """Find an issue by ID in the work payload.

    Returns:
        Tuple of (index, issue) if found, None otherwise.
    """
    for idx, issue in enumerate(work.issues):
        if issue.id == tp_id:
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

    tp_id: BaseIssueID
    description: str = Field(description="Issue rationale/description")

    model_config = ConfigDict(extra="forbid")


class CancelIssueInput(BaseModel):
    """Remove an issue and all its occurrences by id."""

    tp_id: BaseIssueID

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceInput(BaseModel):
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """

    tp_id: BaseIssueID
    file: Annotated[str, StringConstraints(pattern=r"^[^\n]+$")]
    ranges: Annotated[
        list[RangeAtom], Field(min_length=1, description="List of single lines (int) or spans [start,end]")
    ]

    model_config = ConfigDict(extra="forbid")


class SubmitInput(BaseModel):
    """Finalize: the model must state the number of issues it believes it created."""

    issues_count: int = Field(
        ge=0,
        description="Number of issues created. REQUIRED: Use 0 if no issues found. Must exactly match the count of issues you created via upsert_issue.",
    )

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceFilesInput(BaseModel):
    """Add one occurrence spanning multiple files and ranges.

    files: map of file -> list of range atoms (int or [start,end]).
    """

    tp_id: BaseIssueID
    files: dict[Annotated[str, StringConstraints(pattern=r"^[^\n]+$")], list[RangeAtom]]

    model_config = ConfigDict(extra="forbid")


CRITIC_MCP_INSTRUCTIONS = (
    "Critique builder: incrementally add issues and occurrences, then call submit(issues) when complete.\n\n"
    "Workflow:\n"
    "1. For each distinct issue: upsert_issue(tp_id, description) with a concise rationale\n"
    "2. Add occurrences: add_occurrence(tp_id, file, ranges) or add_occurrence_files for multi-file spans\n"
    "3. When finished: ALWAYS call submit(true_positives =N) where N matches the number of issues created\n\n"
    "Important:\n"
    "- If you found ZERO issues, call submit(true_positives =0) - this is required\n"
    "- Do not send plain-text responses or summaries outside tool calls\n"
    "- The submit count must exactly match the number of issues you created\n"
    "- Use report_failure only when truly blocked (access issues, no files matched scope)\n"
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
        result = _find_this_critique(state.work, payload.tp_id)
        if result is not None:
            idx, existing = result
            state.work.issues[idx] = ReportedIssue(
                id=payload.tp_id, rationale=payload.description, occurrences=existing.occurrences
            )
        else:
            state.work.issues.append(ReportedIssue(id=payload.tp_id, rationale=payload.description, occurrences=[]))
        return f"issue {payload.tp_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence"

    @mcp.flat_model()
    async def cancel_issue(payload: CancelIssueInput) -> str:
        """Remove an issue and all its occurrences by id."""
        state.work.issues = [it for it in state.work.issues if it.id != payload.tp_id]
        after_issues = len(state.work.issues)
        after_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"issue {payload.tp_id} canceled. {after_issues} issues ({after_occs} occurrences) noted."

    @mcp.flat_model()
    async def add_occurrence(payload: AddOccurrenceInput) -> str:
        """Add one occurrence for an issue."""
        result = _find_this_critique(state.work, payload.tp_id)
        if result is None:
            raise ToolError(f"Unknown issue '{payload.tp_id}'. Create the issue before adding occurrences.")
        issue = result[1]
        issue.occurrences.append(Occurrence(files={Path(payload.file): _parse_ranges(payload.ranges)}))
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"occurrence recorded for {payload.tp_id}. {total_occs} total occurrences noted."

    @mcp.tool()
    async def show_critique() -> CriticSubmitPayload:
        return state.work

    @mcp.flat_model()
    async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> str:
        """Add one occurrence spanning multiple files/ranges."""
        result = _find_this_critique(state.work, payload.tp_id)
        if result is None:
            raise ToolError(f"Unknown issue '{payload.tp_id}'. Create the issue before adding occurrences.")
        issue = result[1]
        issue.occurrences.append(
            Occurrence(files={Path(p): _parse_ranges(r) for p, r in (payload.files or {}).items()})
        )
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return f"multi-file occurrence recorded for {payload.tp_id}. {total_occs} total occurrences noted."

    @mcp.flat_model()
    async def submit(payload: SubmitInput) -> SimpleOk:
        """Finalize critique and complete the review.

        ALWAYS call this when finished analyzing, even if you found zero issues.
        The 'issues' count must exactly match the number of issues you created via upsert_issue.
        """
        _ensure_not_submitted(state)
        missing = [it.id for it in state.work.issues if not it.occurrences]
        if missing:
            raise ToolError(
                "Each issue must include at least one occurrence. Missing occurrences for: "
                + ", ".join(str(x) for x in missing)
            )
        actual_issues = len(state.work.issues)
        if payload.issues_count != actual_issues:
            raise ToolError(f"Submit count mismatch: reported {payload.issues_count} but found {actual_issues}.")
        state.result = state.work
        return SimpleOk()

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


async def resolve_critic_scope(
    snapshot_slug: SnapshotSlug, files: FileScopeSpec, registry: SnapshotRegistry
) -> ResolvedFileScope:
    """Resolve file scope for critic, handling ALL_FILES_WITH_ISSUES sentinel.

    Args:
        snapshot_slug: Target snapshot
        files: Explicit file set or ALL_FILES_WITH_ISSUES sentinel
        registry: SnapshotRegistry instance (required, always threaded explicitly)

    Returns:
        Resolved file set (guaranteed non-empty)

    Raises:
        ValueError: If sentinel is used but snapshot has no files with issues
    """
    resolved_files: set[Path]
    if files == ALL_FILES_WITH_ISSUES:
        async with registry.load_and_hydrate(snapshot_slug) as hydrated:
            resolved_files = hydrated.files_with_issues()
            if not resolved_files:
                raise ValueError(
                    f"Snapshot '{snapshot_slug}' has no files with ground truth issues. "
                    f"Cannot use '{ALL_FILES_WITH_ISSUES}' sentinel."
                )
    else:
        # Type narrowing: if not ALL_FILES_WITH_ISSUES, must be set[Path]
        resolved_files = cast(set[Path], files)

    return resolved_files


# =============================================================================
# Critic Run Function
# =============================================================================


async def run_critic(
    *,
    input_data: CriticInput,
    client: OpenAIModelProto,
    content_root,
    registry: SnapshotRegistry,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
) -> tuple[CriticSuccess, UUID, UUID]:
    """Execute critic agent to produce candidate issues and persist to DB.

    Sets up critic submit server, Docker exec MCP, and standard handlers (bootstrap,
    database events, AbortIf). Runs agent until submit_result or error is called.

    Returns tuple of (output, critic_run_id, critique_id). Raises RuntimeError on failure.
    Note: Returns IDs only (not ORM objects) to avoid DetachedInstanceError when called
    from within an MCP tool that outlives the session.
    """
    # Fetch system prompt from DB using prompt_sha256 (primary key lookup)
    with get_session() as session:
        prompt_obj = session.get(Prompt, input_data.prompt_sha256)
        if not prompt_obj:
            raise ValueError(f"Prompt not found in database: {input_data.prompt_sha256}")
        system_prompt = prompt_obj.prompt_text

    # Resolve file scope (handles ALL_FILES_WITH_ISSUES sentinel)
    resolved_files = await resolve_critic_scope(input_data.snapshot_slug, input_data.files, registry)

    # Build user prompt from resolved files
    user_prompt = render_prompt_template("critic_user_prompt.j2.md", files=sorted(resolved_files, key=str))

    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        db_run = DBCriticRun(
            id=run_id,
            transcript_id=transcript_id,
            prompt_sha256=input_data.prompt_sha256,
            snapshot_slug=input_data.snapshot_slug,
            model=client.model,
            critique_id=None,  # Will be set in Phase 2 if successful
            prompt_optimization_run_id=input_data.prompt_optimization_run_id,
            files=sorted(str(p) for p in resolved_files),
            output=None,  # Will be set in Phase 2
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial critic run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )

    # Set up critic submit server and state
    critic_state = CriticSubmitState()
    # Use ephemeral=False so critic can persist temporary analysis artifacts, checklists, and reasoning
    wiring = properties_docker_spec(content_root, mount_properties=mount_properties, ephemeral=False)
    comp = Compositor("compositor")
    runtime_server = await wiring.attach(comp)

    # Mount critic submit server
    critic_server = NotifyingFastMCP(CRITIC_SUBMIT_SERVER_NAME, instructions=CRITIC_MCP_INSTRUCTIONS)
    build_critic_submit_tools(critic_server, critic_state)
    await comp.mount_inproc(CRITIC_SUBMIT_SERVER_NAME, critic_server)

    # Set up handlers
    builder = TypedBootstrapBuilder.for_server(runtime_server)
    bootstrap_calls = make_bootstrap_calls_for_inspection(wiring, builder)
    bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

    # Build servers dict for handlers
    servers = {wiring.server_name: runtime_server, CRITIC_SUBMIT_SERVER_NAME: critic_server}

    def _ready_state() -> bool:
        return (critic_state.result is not None) or (critic_state.error is not None)

    handlers: list = [
        bootstrap,
        *build_props_handlers(
            transcript_id=transcript_id,
            verbose_prefix=f"[CRITIC {input_data.snapshot_slug}] " if verbose else None,
            servers=servers,
        ),
        AbortIf(should_abort=_ready_state),
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
            tool_policy=RequireAnyTool(),
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
            critique = Critique(snapshot_slug=input_data.snapshot_slug, payload=output.result.model_dump(mode="json"))
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
        logger.info(f"Updated critic run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    # Return plain IDs, not ORM objects (SQLAlchemy best practice: never return ORM objects from
    # functions that manage their own sessions - they become detached and cause errors)
    return (output, result_id, result_critique_id)
