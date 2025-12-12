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
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import UUID, uuid4

import aiodocker
from fastmcp.client import Client
from fastmcp.exceptions import ToolError
from pydantic import Field, StringConstraints
import typer

if TYPE_CHECKING:
    from fastmcp.tools import FunctionTool

    from adgn.mcp._shared.mounted import Mounted

from adgn.agent.agent import Agent
from adgn.agent.bootstrap import TypedBootstrapBuilder
from adgn.agent.handler import AbortIf, BaseHandler, SequenceHandler
from adgn.agent.loop_control import InjectItems, RequireAnyTool
from adgn.agent.turn_limit import MaxTurnsExceededError, MaxTurnsHandler
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.model import OpenAIModelProto, UserMessage
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.openai_utils.types import ReasoningSummary
from adgn.props.agent_setup import build_props_handlers
from adgn.props.cli.common_options import DEFAULT_MAX_LINES
from adgn.props.critic.exceptions import CriticDidNotSubmitError, CriticExecutionError
from adgn.props.critic.models import (
    CriticContextLengthExceeded,
    CriticInput,
    CriticMaxTurnsExceeded,
    CriticOutput,
    CriticScopeSpec,
    CriticSubmitPayload,
    CriticSuccess,
    ReportedIssue,
    ResolvedFileScope,
)
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun as DBCriticRun, Critique, Prompt, Snapshot
from adgn.props.display import short_uuid
from adgn.props.docker_env import PropertiesDockerCompositor
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


class CriticSubmitServer(EnhancedFastMCP):
    """Critic submit MCP server with typed tool access.

    Provides incremental critique-building tools: upsert_issue, add_occurrence, submit, etc.
    """

    # Tool name constants (for test infrastructure only)
    UPSERT_ISSUE_TOOL_NAME = "upsert_issue"
    ADD_OCCURRENCE_TOOL_NAME = "add_occurrence"
    SUBMIT_TOOL_NAME = "submit"

    # Tool references (assigned in __init__)
    upsert_issue_tool: FunctionTool
    cancel_issue_tool: FunctionTool
    add_occurrence_tool: FunctionTool
    get_critique_tool: FunctionTool
    add_occurrence_files_tool: FunctionTool
    submit_tool: FunctionTool
    report_failure_tool: FunctionTool

    def __init__(self, state: CriticSubmitState):
        """Create critic submit server with state container.

        Args:
            state: State container for submitted result.
        """
        super().__init__("Critic Submit Server", instructions=CRITIC_MCP_INSTRUCTIONS)

        # Helper for parsing line ranges
        def _parse_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
            def _parse_range_atom(a: RangeAtom) -> LineRange:
                if isinstance(a, int):
                    return LineRange(start_line=a, end_line=None)
                if isinstance(a, list) and len(a) == 2 and all(isinstance(x, int) for x in a):
                    return LineRange(start_line=a[0], end_line=a[1])
                raise ValueError(f"Invalid range atom: {a!r}. Expected int or [start, end]")

            return [_parse_range_atom(a) for a in atoms]

        # Register tools - names derived from function names
        async def upsert_issue(payload: UpsertIssueInput) -> str:
            """Create or update an issue header (id + rationale)."""
            result = _find_this_critique(state.work, payload.issue_id)
            if result is not None:
                idx, existing = result
                state.work.issues[idx] = ReportedIssue(
                    id=payload.issue_id, rationale=payload.description, occurrences=existing.occurrences
                )
            else:
                state.work.issues.append(
                    ReportedIssue(id=payload.issue_id, rationale=payload.description, occurrences=[])
                )
            return f"issue {payload.issue_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence"

        async def cancel_issue(payload: CancelIssueInput) -> str:
            """Remove an issue and all its occurrences by id."""
            state.work.issues = [it for it in state.work.issues if it.id != payload.issue_id]
            after_issues = len(state.work.issues)
            after_occs = sum(len(i.occurrences) for i in state.work.issues)
            return f"issue {payload.issue_id} canceled. {after_issues} issues ({after_occs} occurrences) noted."

        async def add_occurrence(payload: AddOccurrenceInput) -> str:
            """Add one occurrence for an issue."""
            result = _find_this_critique(state.work, payload.issue_id)
            if result is None:
                raise ToolError(f"Unknown issue '{payload.issue_id}'. Create the issue before adding occurrences.")
            issue = result[1]
            issue.occurrences.append(
                Occurrence.from_files_dict(files={Path(payload.file): _parse_ranges(payload.ranges)})
            )
            total_occs = sum(len(i.occurrences) for i in state.work.issues)
            return (
                f"occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted. "
                f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
            )

        async def get_critique() -> CriticSubmitPayload:
            """Get current state of the critique (inspection only).

            Use this to double-check what issues the server has collected so far.

            This is a READ-ONLY inspection tool. It does NOT complete the review.
            To finish the review, you MUST call submit().
            """
            return state.work

        async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> str:
            """Add one occurrence spanning multiple files/ranges."""
            result = _find_this_critique(state.work, payload.issue_id)
            if result is None:
                raise ToolError(f"Unknown issue '{payload.issue_id}'. Create the issue before adding occurrences.")
            issue = result[1]
            files_dict: dict[Path, list[LineRange] | None] = {
                Path(fr.path): _parse_ranges(fr.ranges) for fr in payload.files
            }
            issue.occurrences.append(Occurrence.from_files_dict(files=files_dict))
            total_occs = sum(len(i.occurrences) for i in state.work.issues)
            return (
                f"multi-file occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted. "
                f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
            )

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

        async def report_failure(error: ReportFailureInput) -> str:
            """Report that critique could not be completed."""
            _ensure_not_submitted(state)
            state.error = error.message
            raise ToolError(error.message)

        # Assign tool references
        self.upsert_issue_tool = self.flat_model()(upsert_issue)
        self.cancel_issue_tool = self.flat_model()(cancel_issue)
        self.add_occurrence_tool = self.flat_model()(add_occurrence)
        self.get_critique_tool = self.flat_model()(get_critique)
        self.add_occurrence_files_tool = self.flat_model()(add_occurrence_files)
        self.submit_tool = self.flat_model()(submit)
        self.report_failure_tool = self.flat_model()(report_failure)


# =============================================================================
# Critic Compositor (Phase 2 pattern)
# =============================================================================


class CriticCompositor(PropertiesDockerCompositor):
    """Compositor with critic servers pre-mounted.

    Inherits from PropertiesDockerCompositor, which provides:
    - runtime: Docker exec server (mounted by parent class)

    Adds:
    - critic_submit: Critic submission server

    Usage:
        critic_state = CriticSubmitState()

        async with CriticCompositor(
            workspace_root=Path("/workspace"),
            docker_client=docker_client,
            critic_state=critic_state,
            db_conn=DbConnectionConfig(...),
        ) as comp:
            # Access servers via Mounted[T] wrappers:
            exec_tool_name = comp.runtime.server.exec_tool.name
            submit_tool_name = comp.critic_submit.server.submit_tool.name

            # Build bootstrap calls:
            builder = TypedBootstrapBuilder()
            call = builder.call_mounted(comp.runtime, comp.runtime.server.exec_tool, ExecInput(...))
    """

    # Mount prefix constant (for test infrastructure only)
    SUBMIT_PREFIX = "critic_submit"

    # Mounted server attributes (runtime inherited, critic_submit added here)
    critic_submit: Mounted[CriticSubmitServer]

    def __init__(
        self, workspace_root: Path, docker_client: aiodocker.Docker, critic_state: CriticSubmitState, **kwargs
    ):
        """Create compositor with critic dependencies.

        Args:
            workspace_root: Path to workspace directory to mount in container.
            docker_client: Async Docker client (managed by caller).
            critic_state: Critic submit state container (shared with caller).
            **kwargs: Additional arguments passed to PropertiesDockerCompositor
                (mount_properties, db_conn, extra_binds, workspace_mode, network_mode, extra_env, ephemeral)
        """
        super().__init__(workspace_root, docker_client, **kwargs)
        self._critic_state = critic_state

    async def __aenter__(self):
        """Start compositor and mount servers."""
        # Start parent compositor (mounts resources, compositor_meta, runtime)
        await super().__aenter__()

        # Mount critic submit server
        self.critic_submit = await self.mount_inproc(
            "critic_submit", CriticSubmitServer(self._critic_state), pinned=True
        )

        return self


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
    prompt_optimization_run_id: UUID | None,
    docker_client: aiodocker.Docker,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    max_turns: int,
) -> tuple[CriticOutput, UUID, UUID | None]:
    """Execute critic agent to produce candidate issues and persist to DB.

    Sets up critic submit server, Docker exec MCP, and standard handlers (bootstrap,
    database events, AbortIf). Runs agent until submit_result or error is called.

    Returns tuple of (output, critic_run_id, critique_id).
    - output: CriticSuccess if completed, CriticMaxTurnsExceeded if agent ran out of turns
    - critique_id: None if max_turns_exceeded, UUID if success

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

    # Build user prompt from resolved files (just the file list as JSON)
    user_prompt = json.dumps(sorted(str(p) for p in resolved_files), indent=2)

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
        typer.echo(f"[critic] transcript_id={short_uuid(transcript_id)} run_id={short_uuid(run_id)}", err=True)

    # Set up critic submit server and state
    critic_state = CriticSubmitState()
    # Use ephemeral=False so critic can persist temporary analysis artifacts, checklists, and reasoning

    # Use CriticCompositor to bundle server mounting
    async with CriticCompositor(
        workspace_root=content_root,
        docker_client=docker_client,
        critic_state=critic_state,
        mount_properties=mount_properties,
        ephemeral=False,
    ) as comp:
        # Set up handlers
        builder = TypedBootstrapBuilder.for_server(comp.runtime.server)
        bootstrap_calls = make_bootstrap_calls_for_inspection(comp, builder)
        bootstrap = SequenceHandler([InjectItems(items=bootstrap_calls)])

        # Build servers dict for handlers
        servers = {comp.runtime.prefix: comp.runtime.server, comp.critic_submit.prefix: comp.critic_submit.server}

        def _ready_state() -> bool:
            return (critic_state.result is not None) or (critic_state.error is not None)

        handlers: list = [
            bootstrap,
            *build_props_handlers(
                transcript_id=transcript_id,
                verbose_prefix=f"[CRITIC {short_uuid(transcript_id)} {snapshot_split} {input_data.snapshot_slug}] "
                if verbose
                else None,
                servers=servers,
                max_lines=max_lines,
            ),
            AbortIf(should_abort=_ready_state),
            *extra_handlers,
            MaxTurnsHandler(max_turns=max_turns),
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
        # Note: resources and compositor_meta are auto-mounted by base Compositor
        async with Client(comp) as mcp_client:
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
            output: CriticOutput
            try:
                await agent.run()
            except MaxTurnsExceededError:
                # Agent ran out of turns - create max_turns_exceeded output
                logger.warning(
                    f"Critic hit max turns limit ({max_turns}) for {input_data.snapshot_slug}, "
                    f"transcript_id={short_uuid(transcript_id)}"
                )
                output = CriticMaxTurnsExceeded(max_turns=max_turns)
                # Skip state validation - we're terminating early due to turn limit
                # Jump to Phase 2 to persist the max_turns_exceeded output
            except Exception as e:
                # Check if this is a context length exceeded error
                # TODO: Check specifically for openai.BadRequestError with code='context_length_exceeded'
                # instead of string matching - more robust for different API providers
                error_str = str(e).lower()
                if "context_length_exceeded" in error_str or "context window" in error_str:
                    logger.warning(
                        f"Critic hit context length limit for {input_data.snapshot_slug}, "
                        f"transcript_id={short_uuid(transcript_id)}: {e}"
                    )
                    output = CriticContextLengthExceeded(error_message=str(e))
                    # Jump to Phase 2 to persist the context_length_exceeded output
                else:
                    # Re-raise other exceptions
                    raise
            else:
                # Agent completed normally - validate state and create success output
                if critic_state.error is not None:
                    raise CriticExecutionError(f"Critic failed: {critic_state.error}")
                if critic_state.result is None:
                    raise CriticDidNotSubmitError("Critic did not submit")
                output = CriticSuccess(result=critic_state.result)
    # Compositor.__aexit__ unmounts all non-pinned servers and cleans up containers here

    # Phase 2: Update run with output
    with get_session() as session:
        # Create critique if successful
        critique_id = None
        if isinstance(output, CriticSuccess):
            # Convert MCP model to DB model
            from adgn.props.critic.persistence import critic_submit_payload_to_db

            critique = Critique(
                snapshot_slug=input_data.snapshot_slug, payload=critic_submit_payload_to_db(output.result)
            )
            session.add(critique)
            session.flush()
            critique_id = critique.id

        # Update run with output and critique_id
        # Use critic_output_to_db() to convert discriminated union to DB format
        from adgn.props.critic.persistence import critic_output_to_db

        found_run = session.get(DBCriticRun, run_id)
        assert found_run is not None, f"Critic run {run_id} not found in database"
        found_run.output = critic_output_to_db(output)
        found_run.critique_id = critique_id
        session.commit()

        # Extract IDs before session closes (never return ORM objects from functions)
        result_id = found_run.id
        result_critique_id = found_run.critique_id
        logger.info(f"Updated critic run in DB: {transcript_id=}, snapshot_slug={input_data.snapshot_slug}")

    # Return plain IDs, not ORM objects (SQLAlchemy best practice: never return ORM objects from
    # functions that manage their own sessions - they become detached and cause errors)
    return (output, result_id, result_critique_id)
