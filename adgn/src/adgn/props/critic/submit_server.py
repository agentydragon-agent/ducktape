"""MCP server for critic submit workflow.

Provides the submit tool that agents call when done reviewing.
Validates the critique and marks the critic run as complete.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

from fastmcp.exceptions import ToolError
from fastmcp.resources import FunctionResource
from fastmcp.server.auth import AuthProvider
from fastmcp.tools import FunctionTool
from pydantic import BaseModel, Field, StringConstraints

from adgn.mcp._shared.types import MCPMountPrefix
from adgn.mcp.enhanced import EnhancedFastMCP
from adgn.openai_utils.pydantic_strict_mode import OpenAIStrictModeBaseModel
from adgn.props.critic.models import CriticSubmitPayload, Rationale, ReportedIssue as MCPReportedIssue
from adgn.props.critic.persistence import convert_reported_occurrence_orm_to_mcp
from adgn.props.db import get_session
from adgn.props.db.models import CriticRun, CriticRunStatus, ReportedIssue, ReportedIssueOccurrence
from adgn.props.db.snapshots import DBLocationAnchor
from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.models.critic_scopes import CriticScopeSpec
from adgn.props.models.true_positive import LineRange
from adgn.props.snapshot_paths import snapshot_container_path

logger = logging.getLogger(__name__)

# Mount prefix constant for critic submit server
SUBMIT_PREFIX = MCPMountPrefix("critic_submit")

# Resource URIs for MCP resources
CRITIC_SNAPSHOT_SLUG_RESOURCE_URI = "resource://critic_submit/snapshot_slug"
CRITIC_SCOPE_RESOURCE_URI = "resource://critic_submit/scope"

# Incremental tool input models
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


class CriticSubmitInput(OpenAIStrictModeBaseModel):
    """Input for submit tool."""

    issues_count: int
    summary: str


class CriticSubmitResult(BaseModel):
    """Result of submit tool."""

    message: str
    issues_count: int
    occurrences_count: int


class ReportFailureInput(OpenAIStrictModeBaseModel):
    """Input for report_failure tool."""

    message: str


class ReportFailureResult(BaseModel):
    """Result of report_failure."""

    message: str


class CriticSubmitServer(EnhancedFastMCP):
    """MCP server for critic submit operations.

    Provides the submit tool that validates and finalizes a critic run,
    and the report_failure tool for agent-reported failures.

    If incremental_tools=True, also provides upsert_issue, add_occurrence, etc.
    that write directly to PostgreSQL.
    """

    # Tool attributes (always present)
    submit_tool: FunctionTool
    report_failure_tool: FunctionTool

    # Incremental tool attributes (only present if incremental_tools=True)
    upsert_issue_tool: FunctionTool | None = None
    cancel_issue_tool: FunctionTool | None = None
    add_occurrence_tool: FunctionTool | None = None
    add_occurrence_files_tool: FunctionTool | None = None
    get_critique_tool: FunctionTool | None = None

    def __init__(
        self,
        *,
        critic_run_id: UUID,
        snapshot_slug: SnapshotSlug,
        scope: CriticScopeSpec,
        snapshot_mount_path: Path | None = None,
        auth: AuthProvider | None = None,
        incremental_tools: bool = False,
    ):
        """Initialize critic submit server.

        Args:
            critic_run_id: UUID of the critic run to finalize
            snapshot_slug: Snapshot slug (for computing mount path and validating files)
            scope: Scope specification (files to review)
            snapshot_mount_path: Override mount path for testing (default: compute from slug)
            auth: Auth provider for HTTP mode (optional)
            incremental_tools: If True, expose upsert_issue/add_occurrence/etc tools that write to PostgreSQL.
                              If False, agent must write SQL directly (only submit/report_failure exposed).
        """
        super().__init__("Critic Submit", instructions="Submit completed critic review with validation", auth=auth)
        self._critic_run_id = critic_run_id
        self._snapshot_slug = snapshot_slug
        self._scope = scope
        self._snapshot_mount_path = snapshot_mount_path or snapshot_container_path(snapshot_slug)

        # Register resources
        def get_snapshot_slug() -> str:
            """Get the snapshot slug for this critic run."""
            return self._snapshot_slug

        self.snapshot_slug_resource = cast(
            FunctionResource, self.resource(CRITIC_SNAPSHOT_SLUG_RESOURCE_URI)(get_snapshot_slug)
        )

        def get_scope() -> CriticScopeSpec:
            """Get the scope (files to review) for this critic run."""
            return self._scope

        self.scope_resource = cast(FunctionResource, self.resource(CRITIC_SCOPE_RESOURCE_URI)(get_scope))

        def submit(input: CriticSubmitInput) -> CriticSubmitResult:
            """Finalize critic review and validate reported issues.

            Call this when you're done reviewing code. This will:
            1. Validate all reported issues and occurrences
            2. Mark the critic run as completed
            3. Store your summary

            Validations performed:
            - Issues count must match actual reported issues in database
            - Every issue must have at least one occurrence
            - Each occurrence must have at least one location
            - File paths must exist in the mounted snapshot
            - Line ranges must be valid (start_line > 0, end_line >= start_line)
            """
            return self._submit_critique(input.issues_count, input.summary)

        self.submit_tool = self.flat_model()(submit)

        def report_failure(input: ReportFailureInput) -> ReportFailureResult:
            """Report that critique could not be completed.

            Call this when you encounter blocking issues that prevent review completion
            (e.g., no files matched scope, access issues, missing dependencies).

            This marks the run as failed and stores the error message.
            """
            return self._report_failure(input.message)

        self.report_failure_tool = self.flat_model()(report_failure)

        # Incremental tools (only if enabled)
        if incremental_tools:
            self._register_incremental_tools()

    def _register_incremental_tools(self) -> None:
        """Register incremental tools that write to PostgreSQL."""

        def _parse_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
            """Parse range atoms into LineRange objects."""

            def _parse_range_atom(a: RangeAtom) -> LineRange:
                if isinstance(a, int):
                    return LineRange(start_line=a, end_line=None)
                if isinstance(a, list) and len(a) == 2 and all(isinstance(x, int) for x in a):
                    return LineRange(start_line=a[0], end_line=a[1])
                raise ValueError(f"Invalid range atom: {a!r}. Expected int or [start, end]")

            return [_parse_range_atom(a) for a in atoms]

        def upsert_issue(input: UpsertIssueInput) -> str:
            """Create or update an issue header (id + rationale)."""
            with get_session() as session:
                # Check if issue already exists
                existing = (
                    session.query(ReportedIssue)
                    .filter_by(critic_run_id=self._critic_run_id, issue_id=input.issue_id)
                    .first()
                )

                if existing:
                    # Update existing issue
                    existing.rationale = input.description
                else:
                    # Create new issue
                    issue = ReportedIssue(
                        critic_run_id=self._critic_run_id, issue_id=input.issue_id, rationale=input.description
                    )
                    session.add(issue)

                session.commit()

            return f"issue {input.issue_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence"

        self.upsert_issue_tool = self.flat_model()(upsert_issue)

        def cancel_issue(input: CancelIssueInput) -> str:
            """Remove an issue and all its occurrences by id."""
            with get_session() as session:
                # Delete issue (cascade will delete occurrences)
                session.query(ReportedIssue).filter_by(
                    critic_run_id=self._critic_run_id, issue_id=input.issue_id
                ).delete()

                # Count remaining
                after_issues = session.query(ReportedIssue).filter_by(critic_run_id=self._critic_run_id).count()
                after_occs = session.query(ReportedIssueOccurrence).filter_by(critic_run_id=self._critic_run_id).count()

                session.commit()

            return f"issue {input.issue_id} canceled. {after_issues} issues ({after_occs} occurrences) noted."

        self.cancel_issue_tool = self.flat_model()(cancel_issue)

        def add_occurrence(input: AddOccurrenceInput) -> str:
            """Add one occurrence for an issue."""
            with get_session() as session:
                # Check issue exists
                issue = (
                    session.query(ReportedIssue)
                    .filter_by(critic_run_id=self._critic_run_id, issue_id=input.issue_id)
                    .first()
                )
                if issue is None:
                    raise ToolError(f"Unknown issue '{input.issue_id}'. Create the issue before adding occurrences.")

                # Parse ranges
                ranges = _parse_ranges(input.ranges)

                # Create occurrence with single file location
                locations = [
                    DBLocationAnchor(file=input.file, start_line=r.start_line, end_line=r.end_line) for r in ranges
                ]

                occurrence = ReportedIssueOccurrence(
                    critic_run_id=self._critic_run_id, reported_issue_id=input.issue_id, locations=locations
                )
                session.add(occurrence)

                # Count total occurrences
                session.flush()
                total_occs = session.query(ReportedIssueOccurrence).filter_by(critic_run_id=self._critic_run_id).count()

                session.commit()

            return (
                f"occurrence recorded for {input.issue_id}. {total_occs} total occurrences noted. "
                f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
            )

        self.add_occurrence_tool = self.flat_model()(add_occurrence)

        def add_occurrence_files(input: AddOccurrenceFilesInput) -> str:
            """Add one occurrence spanning multiple files/ranges."""
            with get_session() as session:
                # Check issue exists
                issue = (
                    session.query(ReportedIssue)
                    .filter_by(critic_run_id=self._critic_run_id, issue_id=input.issue_id)
                    .first()
                )
                if issue is None:
                    raise ToolError(f"Unknown issue '{input.issue_id}'. Create the issue before adding occurrences.")

                # Build locations list from all files
                locations: list[DBLocationAnchor] = []
                for file_ranges in input.files:
                    ranges = _parse_ranges(file_ranges.ranges)
                    for r in ranges:
                        locations.append(
                            DBLocationAnchor(file=file_ranges.path, start_line=r.start_line, end_line=r.end_line)
                        )

                occurrence = ReportedIssueOccurrence(
                    critic_run_id=self._critic_run_id, reported_issue_id=input.issue_id, locations=locations
                )
                session.add(occurrence)

                # Count total occurrences
                session.flush()
                total_occs = session.query(ReportedIssueOccurrence).filter_by(critic_run_id=self._critic_run_id).count()

                session.commit()

            return (
                f"multi-file occurrence recorded for {input.issue_id}. {total_occs} total occurrences noted. "
                f"If this is the last occurrence and you have no more issues to report, call submit() to finalize your critique."
            )

        self.add_occurrence_files_tool = self.flat_model()(add_occurrence_files)

        def get_critique() -> CriticSubmitPayload:
            """Get current state of the critique (inspection only).

            Use this to double-check what issues the server has collected so far.

            This is a READ-ONLY inspection tool. It does NOT complete the review.
            To finish the review, you MUST call submit().
            """
            with get_session() as session:
                issues = session.query(ReportedIssue).filter_by(critic_run_id=self._critic_run_id).all()

                mcp_issues = [
                    MCPReportedIssue(
                        id=issue.issue_id,
                        rationale=Rationale(issue.rationale),
                        occurrences=[
                            convert_reported_occurrence_orm_to_mcp(occ)
                            for occ in session.query(ReportedIssueOccurrence)
                            .filter_by(critic_run_id=self._critic_run_id, reported_issue_id=issue.issue_id)
                            .all()
                        ],
                    )
                    for issue in issues
                ]

                return CriticSubmitPayload(issues=mcp_issues, notes_md=None)

        self.get_critique_tool = self.flat_model()(get_critique)

    def _submit_critique(self, issues_count: int, summary: str) -> CriticSubmitResult:
        """Submit critique with validation."""
        with get_session() as session:
            # Load critic run
            critic_run = session.get(CriticRun, self._critic_run_id)
            if critic_run is None:
                raise ToolError(f"Critic run {self._critic_run_id} not found")

            if critic_run.status == CriticRunStatus.COMPLETED:
                raise ToolError(f"Critic run {self._critic_run_id} already completed")

            # Load reported issues and occurrences
            issues = session.query(ReportedIssue).filter_by(critic_run_id=self._critic_run_id).all()

            # Validate issues count matches
            actual_issues_count = len(issues)
            if issues_count != actual_issues_count:
                raise ToolError(
                    f"Issues count mismatch: expected {issues_count} but found {actual_issues_count} in database"
                )

            total_occurrences = 0
            for issue in issues:
                occurrences = (
                    session.query(ReportedIssueOccurrence)
                    .filter_by(critic_run_id=self._critic_run_id, reported_issue_id=issue.issue_id)
                    .all()
                )

                # Validate that issue has at least one occurrence
                if len(occurrences) == 0:
                    raise ToolError(
                        f"Issue '{issue.issue_id}' has no occurrences. "
                        f"Every issue must have at least one occurrence showing where it occurs in the code."
                    )

                total_occurrences += len(occurrences)

                # Validate each occurrence
                for occ in occurrences:
                    self._validate_occurrence(occ)

            # Mark run as completed
            critic_run.status = CriticRunStatus.COMPLETED
            critic_run.completion_summary = summary
            session.commit()

            logger.info(
                "Critic run %s completed: %d issues, %d occurrences",
                self._critic_run_id,
                len(issues),
                total_occurrences,
            )

            return CriticSubmitResult(
                message=f"Review completed successfully with {len(issues)} issues",
                issues_count=len(issues),
                occurrences_count=total_occurrences,
            )

    def _report_failure(self, message: str) -> ReportFailureResult:
        """Report critique failure with message."""
        with get_session() as session:
            # Load critic run
            critic_run = session.get(CriticRun, self._critic_run_id)
            if critic_run is None:
                raise ToolError(f"Critic run {self._critic_run_id} not found")

            if critic_run.status == CriticRunStatus.COMPLETED:
                raise ToolError(f"Critic run {self._critic_run_id} already completed")

            if critic_run.status == CriticRunStatus.REPORTED_FAILURE:
                raise ToolError(f"Critic run {self._critic_run_id} already reported failure")

            # Mark run as failed with message
            critic_run.status = CriticRunStatus.REPORTED_FAILURE
            critic_run.completion_summary = message
            session.commit()

            logger.info("Critic run %s reported failure: %s", self._critic_run_id, message)

            return ReportFailureResult(message=f"Failure reported: {message}")

    def _validate_occurrence(self, occ: ReportedIssueOccurrence) -> None:
        """Validate a single occurrence.

        Raises ToolError if validation fails.
        """
        # Check that locations is not empty
        if not occ.locations or len(occ.locations) == 0:
            raise ToolError(f"Occurrence {occ.id} must have at least one location")

        # Validate each location
        for i, loc in enumerate(occ.locations):
            # Type check (should be DBLocationAnchor from Pydantic)
            if not isinstance(loc, DBLocationAnchor):
                raise ToolError(f"Location {i} must be a DBLocationAnchor, got {type(loc)}")

            # TODO: Refactor mounted snapshot validation
            # This check assumes snapshot is mounted at _snapshot_mount_path, which couples
            # validation to the execution environment (Docker container with mounts).
            # Should abstract this to support:
            # - Testing without actual mounts (mock filesystem)
            # - Validation against git refs/bundles without hydration
            # - Decoupling submit validation from Docker runtime

            # Validate file path exists
            file_full_path = self._snapshot_mount_path / loc.file

            if not file_full_path.exists():
                raise ToolError(
                    f"File path '{loc.file}' (location {i}) does not exist in snapshot at {self._snapshot_mount_path}"
                )

            if not file_full_path.is_file():
                raise ToolError(f"Path '{loc.file}' (location {i}) exists but is not a file")

            # Validate line ranges if provided
            if loc.start_line is not None:
                if loc.start_line <= 0:
                    raise ToolError(f"Location {i}: start_line must be > 0, got {loc.start_line}")

                if loc.end_line is not None and loc.end_line < loc.start_line:
                    raise ToolError(f"Location {i}: end_line ({loc.end_line}) must be >= start_line ({loc.start_line})")


def make_critic_submit_server(
    *,
    critic_run_id: UUID,
    snapshot_slug: SnapshotSlug,
    scope: CriticScopeSpec,
    snapshot_mount_path: Path | None = None,
    auth: AuthProvider | None = None,
    incremental_tools: bool = False,
) -> CriticSubmitServer:
    """Factory function for critic submit server.

    Args:
        critic_run_id: UUID of the critic run to finalize
        snapshot_slug: Snapshot slug (for computing mount path and validating files)
        scope: Scope specification (files to review)
        snapshot_mount_path: Override mount path for testing (default: compute from slug)
        auth: Auth provider for HTTP mode (optional)
        incremental_tools: If True, expose upsert_issue/add_occurrence/etc tools

    Returns:
        Configured CriticSubmitServer instance
    """
    return CriticSubmitServer(
        critic_run_id=critic_run_id,
        snapshot_slug=snapshot_slug,
        scope=scope,
        snapshot_mount_path=snapshot_mount_path,
        auth=auth,
        incremental_tools=incremental_tools,
    )
