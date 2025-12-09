"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via ``submit``.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call ``submit(issues_count)`` after building the critique using the incremental tools.

TODO: Enable compaction for critic runs to reduce transcript size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import typer

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder
from adgn.agent.handler import AbortIf, BaseHandler, SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.constants import CRITIC_SUBMIT_SERVER_NAME
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.models import (
    CriticInput,
    CriticScopeSpec,
    CriticSubmitPayload,
    CriticSuccess,
    ReportedIssue,
    ResolvedFileScope,
)
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Critique, Prompt, Snapshot
from adgn.props.docker_env import properties_docker_spec
from adgn.props.files_hash import hash_file_set
from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.lint_issue import make_bootstrap_calls_for_inspection
from adgn.props.models.critic_scopes import AllFilesScope, ExplicitFileScope
from adgn.props.models.true_positive import LineRange, Occurrence
from adgn.props.prompts.util import render_prompt_template

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
    work: CriticSubmitPayload = field(default_factory=lambda: CriticSubmitPayload(issues=[], notes_md=None))


class CriticFailure(BaseModel):
    """Failed critic output (not used in current API but kept for potential future use)."""

    tag: Literal["failure"] = "failure"
    error: str = Field(description="Error message explaining why critique failed")

    model_config = ConfigDict(frozen=True)


# Discriminated union for critic output (not currently used but defined for completeness)
CriticOutput = Annotated[CriticSuccess | CriticFailure, Field(discriminator="tag")]


class ReportFailureInput(OpenAIStrictModeBaseModel):
    """Input for report_failure tool."""

    message: str = Field(description="Error message explaining why critique could not be completed")


# =============================================================================
# Internal Helper Functions
# =============================================================================


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


class UpsertIssueInput(OpenAIStrictModeBaseModel):
    """Create or update an issue header (id + rationale)."""

    issue_id: BaseIssueID
    description: str = Field(description="Issue rationale/description")


class CancelIssueInput(OpenAIStrictModeBaseModel):
    """Remove an issue and all its occurrences by id."""

    issue_id: BaseIssueID


class AddOccurrenceInput(OpenAIStrictModeBaseModel):
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """

    issue_id: BaseIssueID
    file: Annotated[str, StringConstraints(pattern=r"^[^\n]+$")]
    ranges: Annotated[
        list[RangeAtom], Field(min_length=1, description="List of single lines (int) or spans [start,end]")
    ]


class SubmitInput(OpenAIStrictModeBaseModel):
    """Finalize: the model must state the number of issues it believes it created."""

    issues_count: int = Field(
        ge=0,
        description="Number of issues created. REQUIRED: Use 0 if no issues found. Must exactly match the count of issues you created via upsert_issue.",
    )


class FileRanges(OpenAIStrictModeBaseModel):
    """File path with associated line ranges."""

    path: str
    ranges: list[RangeAtom]


class AddOccurrenceFilesInput(OpenAIStrictModeBaseModel):
    """Add one occurrence spanning multiple files and ranges.

    files: list of files with their line ranges.
    """

    issue_id: BaseIssueID
    files: list[FileRanges]


CRITIC_MCP_INSTRUCTIONS = (
    "Critique builder: incrementally add issues and occurrences, then call submit() when complete.\n\n"
    "Workflow:\n"
    "1. For each distinct issue: upsert_issue(issue_id, description) with a concise rationale\n"
    "2. Add occurrences: add_occurrence(issue_id, file, ranges) or add_occurrence_files for multi-file spans\n"
    "3. When finished reviewing: ALWAYS call submit(issues_count=N) where N matches the number of issues created\n\n"
    "Important:\n"
    "- If you found ZERO issues, call submit(issues_count=0) - this is required\n"
    "- Do not send plain-text responses or summaries outside tool calls\n"
    "- The submit count must exactly match the number of issues you created\n"
    "- Use report_failure only when truly blocked (access issues, no files matched scope)\n"
    "- When done with your analysis, call submit() to finalize your critique\n"
)


def build_critic_submit_tools(mcp: EnhancedFastMCP, state: CriticSubmitState) -> None:
    """Register critic submit tools on the provided server (tools-builder pattern)."""

    def _parse_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
        def _parse_range_atom(a: RangeAtom) -> LineRange:
            if isinstance(a, int):
                return LineRange(start_line=a, end_line=None)
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
        issue.occurrences.append(Occurrence.from_files_dict(files={Path(payload.file): _parse_ranges(payload.ranges)}))
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return (
            f"occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted. "
            f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
        )

    @mcp.flat_model()
    async def get_critique() -> CriticSubmitPayload:
        """Get current state of the critique (inspection only).

        Use this to double-check what issues the server has collected so far.

        This is a READ-ONLY inspection tool. It does NOT complete the review.
        To finish the review, you MUST call submit().
        """
        return state.work

    @mcp.flat_model()
    async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> str:
        """Add one occurrence spanning multiple files/ranges."""
        result = _find_this_critique(state.work, payload.issue_id)
        if result is None:
            raise ToolError(f"Unknown issue '{payload.issue_id}'. Create the issue before adding occurrences.")
        issue = result[1]
        # Convert list of FileRanges to dict for Occurrence.from_files_dict
        files_dict: dict[Path, list[LineRange] | None] = {
            Path(fr.path): _parse_ranges(fr.ranges) for fr in payload.files
        }
        issue.occurrences.append(Occurrence.from_files_dict(files=files_dict))
        total_occs = sum(len(i.occurrences) for i in state.work.issues)
        return (
            f"multi-file occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted. "
            f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
        )

    @mcp.flat_model()
    async def submit(payload: SubmitInput) -> SimpleOk:
        """**REQUIRED FINAL STEP** - Submit your critique and end the review task.

        This is the ONE AND ONLY gate to complete the critique task. You MUST call this function
        to signal completion, whether you found issues or not. Until you call submit(), you will
        continue being prompted to take actions.

        Call this when you have finished your analysis, even if you found zero issues.

        Args:
            issues_count: Number of issues you created via upsert_issue (can be 0)
            notes_md: Optional notes about your review

        The issues_count must exactly match the number of issues you created via upsert_issue.
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
    files = [_format_file_ranges(fo.path, fo.ranges) for fo in occ.files]
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


async def resolve_critic_scope(snapshot_slug: SnapshotSlug, files: CriticScopeSpec) -> ResolvedFileScope:
    """Resolve file scope for critic, handling discriminated union.

    Loads files with issues from database (no jsonnet evaluation).

    Args:
        snapshot_slug: Target snapshot
        files: Discriminated union of ExplicitFileScope or AllFilesScope

    Returns:
        Resolved file set (guaranteed non-empty)

    Raises:
        ValueError: If AllFilesScope is used but snapshot has no files with issues
    """
    resolved_files: set[Path]
    if isinstance(files, AllFilesScope):
        # Load files with issues from database (not from jsonnet!)
        with get_session() as session:
            snapshot = session.query(Snapshot).filter_by(slug=snapshot_slug).one()
            resolved_files = snapshot.files_with_issues()
            if not resolved_files:
                raise ValueError(
                    f"Snapshot '{snapshot_slug}' has no files with ground truth issues. "
                    "Cannot use AllFilesScope sentinel."
                )
    else:
        # Type narrowing: must be ExplicitFileScope
        assert isinstance(files, ExplicitFileScope)
        resolved_files = {Path(f) for f in files.files}

    return resolved_files


# =============================================================================
# Critic Run Function
# =============================================================================


async def run_critic(
    *,
    input_data: CriticInput,
    client: OpenAIModelProto,
    content_root,
    prompt_optimization_run_id: UUID | None = None,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
) -> tuple[CriticSuccess, UUID, UUID]:
    """Execute critic agent to produce candidate issues and persist to DB.

    Sets up critic submit server, Docker exec MCP, and standard handlers (bootstrap,
    database events, AbortIf). Runs agent until submit_result or error is called.

    Returns tuple of (output, critic_run_id, critique_id). Raises RuntimeError on failure.
    Note: Returns IDs only (not ORM objects) to avoid DetachedInstanceError when called
    from within an MCP tool that outlives the session.
    """
    # Fetch optimized prompt from DB using prompt_sha256 (primary key lookup)
    with get_session() as session:
        prompt_obj = session.get(Prompt, input_data.prompt_sha256)
        if not prompt_obj:
            raise ValueError(f"Prompt not found in database: {input_data.prompt_sha256}")
        optimized_prompt = prompt_obj.prompt_text

    # Resolve file scope (handles ALL_FILES_WITH_ISSUES sentinel - loads from DB)
    resolved_files = await resolve_critic_scope(input_data.snapshot_slug, input_data.files)

    # Build user prompt from resolved files (just the file list)
    user_prompt = render_prompt_template(
        "critic/prompts/critic_user_prompt.j2.md", files=sorted(resolved_files, key=str)
    )

    # Generate unique IDs for this run
    run_id = uuid4()
    transcript_id = uuid4()

    # Phase 1: Write initial run to DB (BEFORE agent runs - FK constraint!)
    with get_session() as session:
        # Fetch snapshot to get split for verbose prefix
        snapshot = session.query(Snapshot).filter_by(slug=input_data.snapshot_slug).one()
        snapshot_split = snapshot.split

        db_run = DBCriticRun(
            id=run_id,
            transcript_id=transcript_id,
            prompt_sha256=input_data.prompt_sha256,
            snapshot_slug=input_data.snapshot_slug,
            model=client.model,
            critique_id=None,  # Will be set in Phase 2 if successful
            prompt_optimization_run_id=prompt_optimization_run_id,
            files=sorted(str(p) for p in resolved_files),
            files_hash=hash_file_set(resolved_files),
            output=None,  # Will be set in Phase 2
        )
        session.add(db_run)
        session.commit()
        logger.info(
            f"Created initial critic run in DB: {run_id=}, {transcript_id=}, snapshot_slug={input_data.snapshot_slug}"
        )
        # Print IDs early to console for easy retrieval if run is interrupted
        typer.echo(f"[critic] transcript_id={transcript_id} run_id={run_id}", err=True)

    # Set up critic submit server and state
    critic_state = CriticSubmitState()
    # Use ephemeral=False so critic can persist temporary analysis artifacts, checklists, and reasoning
    wiring = properties_docker_spec(content_root, mount_properties=mount_properties, ephemeral=False)

    # Use Compositor as async context manager to ensure cleanup
    async with Compositor() as comp:
        runtime_server = await wiring.attach(comp)

        # Mount critic submit server
        critic_server = EnhancedFastMCP(CRITIC_SUBMIT_SERVER_NAME, instructions=CRITIC_MCP_INSTRUCTIONS)
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
                verbose_prefix=f"[CRITIC {str(transcript_id)[:8]} {snapshot_split} {input_data.snapshot_slug}] "
                if verbose
                else None,
                servers=servers,
                max_lines=max_lines,
            ),
            AbortIf(should_abort=_ready_state),
            *extra_handlers,
        ]

        # Build combined dynamic instructions by rendering the template
        async def _build_critic_instructions() -> str:
            """Build critic system instructions by rendering critic_system.j2.md template.

            The template has two placeholders:
            1. {{ compositor_instructions }} - MCP wiring: servers, tools, resources
            2. {{ optimized_prompt }} - The prompt being tested/optimized
            """
            compositor_instructions = comp.render_agent_dynamic_instructions()
            return render_prompt_template(
                "critic/prompts/critic_system.j2.md",
                compositor_instructions=compositor_instructions,
                optimized_prompt=optimized_prompt,
            )

        # Run critic agent
        async with Client(comp) as mcp_client:
            await mount_standard_inproc_servers(compositor=comp)
            agent = await Agent.create(
                mcp_client=mcp_client,
                client=client,
                handlers=handlers,
                parallel_tool_calls=True,
                tool_policy=RequireAnyTool(),
                reasoning_summary=ReasoningSummary.detailed,
                dynamic_instructions=_build_critic_instructions,
            )
            agent.insert_message(UserMessage.text(user_prompt))
            await agent.run()
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

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
