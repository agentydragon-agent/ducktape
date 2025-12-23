"""Reminder handler for improvement agent termination logic.

Checks if the improvement agent has created a definition that:
1. Has completed evals on ALL allowed_examples
2. Beats the average of baseline definitions on total issues found

When condition is met, the handler aborts the agent loop (task complete).
Otherwise, it injects a reminder message explaining what's blocking.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, InjectItems, LoopDecision, NoAction
from adgn.openai_utils.model import UserMessage
from adgn.props.agent_types import ImprovementTypeConfig
from adgn.props.db import get_session
from adgn.props.db.config import DatabaseConfig
from adgn.props.models.examples import SingleFileSetExample

logger = logging.getLogger(__name__)


class TerminationStatus(BaseModel):
    """Status of termination condition check."""

    should_terminate: bool
    """True if agent has created a definition that beats baseline."""

    blocking_message: str | None
    """Human-readable explanation of what's blocking (if not terminated)."""

    # Details for logging/debugging
    baseline_avg_issues: float | None
    """Average issues found by baseline definitions (None if no baselines with evals)."""

    best_candidate_issues: float | None
    """Issues found by the best candidate definition (None if no candidates)."""

    best_candidate_id: str | None
    """ID of the best candidate definition (None if no candidates)."""

    missing_evals_count: int
    """Number of (definition, example) pairs missing evals."""


def check_termination_condition(
    session: Session, improvement_run_id: UUID, type_config: ImprovementTypeConfig
) -> TerminationStatus:
    """Check if improvement agent should terminate.

    Termination condition:
    - Agent has created at least one definition
    - That definition has completed evals on ALL allowed_examples
    - Total issues found is greater than average of baseline definitions

    Args:
        session: SQLAlchemy session (with RLS - must be admin or improvement agent user)
        improvement_run_id: The improvement agent's run ID
        type_config: ImprovementTypeConfig with baseline_definition_ids and allowed_examples

    Returns:
        TerminationStatus with decision and details
    """
    baseline_ids = type_config.baseline_definition_ids
    allowed_examples = type_config.allowed_examples

    if not baseline_ids:
        return TerminationStatus(
            should_terminate=False,
            blocking_message="No baseline definitions specified in type_config.",
            baseline_avg_issues=None,
            best_candidate_issues=None,
            best_candidate_id=None,
            missing_evals_count=0,
        )

    if not allowed_examples:
        return TerminationStatus(
            should_terminate=False,
            blocking_message="No allowed_examples specified in type_config.",
            baseline_avg_issues=None,
            best_candidate_issues=None,
            best_candidate_id=None,
            missing_evals_count=0,
        )

    # Build list of ExampleSpec for SQL queries
    # ExampleSpec is frozen and hashable - use directly
    n_examples = len(allowed_examples)

    # Query 1: Get baseline average issues found
    # Uses occurrence_credits view to compute total issues (sum of credits) per definition
    # then average across baseline definitions
    # Note: Uses (snapshot_slug, example_kind, files_hash) composite key
    baseline_query = text("""
        WITH allowed_examples AS (
            SELECT
                unnest(:snapshot_slugs) AS snapshot_slug,
                unnest(:example_kinds) AS example_kind,
                unnest(:files_hashes) AS files_hash
        ),
        baseline_issues AS (
            SELECT
                oc.critic_definition_id AS agent_definition_id,
                SUM(oc.found_credit) as total_issues
            FROM occurrence_credits oc
            JOIN allowed_examples ae ON (
                oc.snapshot_slug = ae.snapshot_slug
                AND oc.example_kind::text = ae.example_kind
                AND COALESCE(oc.files_hash, '') = COALESCE(ae.files_hash, '')
            )
            WHERE oc.critic_definition_id = ANY(:baseline_ids)
            GROUP BY oc.critic_definition_id
        )
        SELECT AVG(total_issues) as avg_issues
        FROM baseline_issues
    """).bindparams(
        bindparam("baseline_ids", type_=ARRAY(String)),
        bindparam("snapshot_slugs", type_=ARRAY(String)),
        bindparam("example_kinds", type_=ARRAY(String)),
        bindparam("files_hashes", type_=ARRAY(String)),
    )

    # Build parallel lists for the composite key (snapshot_slug, example_kind, files_hash)
    snapshot_slugs = [str(ex.snapshot_slug) for ex in allowed_examples]
    example_kinds = [ex.kind for ex in allowed_examples]  # "whole_snapshot" or "file_set"
    files_hashes = [ex.files_hash if isinstance(ex, SingleFileSetExample) else "" for ex in allowed_examples]

    baseline_result = session.execute(
        baseline_query,
        {
            "baseline_ids": baseline_ids,
            "snapshot_slugs": snapshot_slugs,
            "example_kinds": example_kinds,
            "files_hashes": files_hashes,
        },
    ).fetchone()

    baseline_avg = baseline_result.avg_issues if baseline_result and baseline_result.avg_issues else None

    # Query 2: Get definitions created by this improvement run
    # and their total issues found on allowed_examples
    # Note: Uses (snapshot_slug, example_kind, files_hash) composite key
    candidate_query = text("""
        WITH allowed_examples AS (
            SELECT
                unnest(:snapshot_slugs) AS snapshot_slug,
                unnest(:example_kinds) AS example_kind,
                unnest(:files_hashes) AS files_hash
        ),
        candidate_defs AS (
            SELECT id as agent_definition_id
            FROM agent_definitions
            WHERE created_by_agent_run_id = :improvement_run_id
        ),
        candidate_coverage AS (
            -- For each candidate, count how many of the allowed examples have evals
            SELECT
                cd.agent_definition_id,
                COUNT(DISTINCT (oc.snapshot_slug, oc.example_kind, COALESCE(oc.files_hash, ''))) as covered_examples,
                SUM(oc.found_credit) as total_issues
            FROM candidate_defs cd
            LEFT JOIN occurrence_credits oc ON oc.critic_definition_id = cd.agent_definition_id
            LEFT JOIN allowed_examples ae ON (
                oc.snapshot_slug = ae.snapshot_slug
                AND oc.example_kind::text = ae.example_kind
                AND COALESCE(oc.files_hash, '') = COALESCE(ae.files_hash, '')
            )
            WHERE ae.snapshot_slug IS NOT NULL OR oc.snapshot_slug IS NULL
            GROUP BY cd.agent_definition_id
        )
        SELECT
            agent_definition_id,
            covered_examples,
            total_issues
        FROM candidate_coverage
        ORDER BY total_issues DESC NULLS LAST
    """).bindparams(
        bindparam("snapshot_slugs", type_=ARRAY(String)),
        bindparam("example_kinds", type_=ARRAY(String)),
        bindparam("files_hashes", type_=ARRAY(String)),
    )

    candidate_results = session.execute(
        candidate_query,
        {
            "improvement_run_id": str(improvement_run_id),
            "snapshot_slugs": snapshot_slugs,
            "example_kinds": example_kinds,
            "files_hashes": files_hashes,
        },
    ).fetchall()

    # Find best fully-covered candidate
    best_candidate_id: str | None = None
    best_candidate_issues: float | None = None
    best_partial_candidate_id: str | None = None
    best_partial_issues: float | None = None
    best_partial_coverage: int = 0

    for row in candidate_results:
        covered = row.covered_examples or 0
        issues = row.total_issues or 0.0

        if covered >= n_examples:
            # Fully covered - check if better than current best
            if best_candidate_issues is None or issues > best_candidate_issues:
                best_candidate_id = row.agent_definition_id
                best_candidate_issues = issues
        elif covered > best_partial_coverage or (
            covered == best_partial_coverage and (best_partial_issues is None or issues > best_partial_issues)
        ):
            # Partially covered - track for blocking message
            best_partial_candidate_id = row.agent_definition_id
            best_partial_issues = issues
            best_partial_coverage = covered

    # Check missing baseline evals
    # Note: Uses (snapshot_slug, example_kind, files_hash) composite key
    missing_baseline_query = text("""
        WITH required_examples AS (
            SELECT
                unnest(:snapshot_slugs) as snapshot_slug,
                unnest(:example_kinds) as example_kind,
                unnest(:files_hashes) as files_hash
        ),
        baseline_coverage AS (
            SELECT
                critic_definition_id AS agent_definition_id,
                snapshot_slug,
                example_kind,
                files_hash
            FROM occurrence_credits
            WHERE critic_definition_id = ANY(:baseline_ids)
            GROUP BY critic_definition_id, snapshot_slug, example_kind, files_hash
        )
        SELECT COUNT(*) as missing_count
        FROM (
            SELECT b.agent_definition_id, r.snapshot_slug, r.example_kind, r.files_hash
            FROM unnest(:baseline_ids) as b(agent_definition_id)
            CROSS JOIN required_examples r
            WHERE NOT EXISTS (
                SELECT 1 FROM baseline_coverage bc
                WHERE bc.agent_definition_id = b.agent_definition_id
                  AND bc.snapshot_slug = r.snapshot_slug
                  AND bc.example_kind::text = r.example_kind
                  AND COALESCE(bc.files_hash, '') = COALESCE(r.files_hash, '')
            )
        ) missing
    """).bindparams(
        bindparam("baseline_ids", type_=ARRAY(String)),
        bindparam("snapshot_slugs", type_=ARRAY(String)),
        bindparam("example_kinds", type_=ARRAY(String)),
        bindparam("files_hashes", type_=ARRAY(String)),
    )

    missing_result = session.execute(
        missing_baseline_query,
        {
            "baseline_ids": baseline_ids,
            "snapshot_slugs": snapshot_slugs,
            "example_kinds": example_kinds,
            "files_hashes": files_hashes,
        },
    ).fetchone()

    missing_baseline_evals = missing_result.missing_count if missing_result else 0

    # Decision logic
    if best_candidate_id is not None and best_candidate_issues is not None:
        # We have a fully-covered candidate
        if baseline_avg is None:
            # No baseline evals - need to run them first
            return TerminationStatus(
                should_terminate=False,
                blocking_message=(
                    f"Definition '{best_candidate_id}' has {best_candidate_issues:.1f} issues found, "
                    f"but baseline definitions have no evals yet. "
                    f"Run evals for {missing_baseline_evals} missing (baseline, example) pairs."
                ),
                baseline_avg_issues=None,
                best_candidate_issues=best_candidate_issues,
                best_candidate_id=best_candidate_id,
                missing_evals_count=missing_baseline_evals,
            )

        if best_candidate_issues > baseline_avg:
            # Success! Terminate.
            return TerminationStatus(
                should_terminate=True,
                blocking_message=None,
                baseline_avg_issues=baseline_avg,
                best_candidate_issues=best_candidate_issues,
                best_candidate_id=best_candidate_id,
                missing_evals_count=0,
            )

        # Candidate doesn't beat baseline
        return TerminationStatus(
            should_terminate=False,
            blocking_message=(
                f"Definition '{best_candidate_id}' found {best_candidate_issues:.1f} issues, "
                f"but baseline average is {baseline_avg:.1f}. "
                f"Need to find more issues or create a better definition."
            ),
            baseline_avg_issues=baseline_avg,
            best_candidate_issues=best_candidate_issues,
            best_candidate_id=best_candidate_id,
            missing_evals_count=0,
        )

    # No fully-covered candidate yet
    if not candidate_results:
        # No candidates created at all
        return TerminationStatus(
            should_terminate=False,
            blocking_message=(
                "No definitions created yet. "
                "Create an improved definition at /workspace/improved/ and call create_definition."
            ),
            baseline_avg_issues=baseline_avg,
            best_candidate_issues=None,
            best_candidate_id=None,
            missing_evals_count=missing_baseline_evals,
        )

    # Have partial candidate(s)
    missing_examples = n_examples - best_partial_coverage
    return TerminationStatus(
        should_terminate=False,
        blocking_message=(
            f"Definition '{best_partial_candidate_id}' has evals for {best_partial_coverage}/{n_examples} examples. "
            f"Run evals for the remaining {missing_examples} examples to check if it beats baseline "
            f"(baseline avg: {baseline_avg:.1f} issues)."
            if baseline_avg
            else f"Definition '{best_partial_candidate_id}' has evals for {best_partial_coverage}/{n_examples} examples. "
            f"Run evals for the remaining {missing_examples} examples. "
            f"Also run baseline evals ({missing_baseline_evals} missing) to establish comparison target."
        ),
        baseline_avg_issues=baseline_avg,
        best_candidate_issues=best_partial_issues,
        best_candidate_id=best_partial_candidate_id,
        missing_evals_count=missing_examples + missing_baseline_evals,
    )


class ImprovementReminderHandler(BaseHandler):
    """Handler that checks termination condition and injects reminders.

    On each sampling iteration:
    1. Check if termination condition is met (agent created a definition that beats baseline)
    2. If met, abort the loop (task complete)
    3. If not met, inject a reminder message explaining what's blocking

    The reminder is injected when:
    - Assistant sends a text message (indicating confusion about what to do)
    - Periodically to keep agent on track (every N turns after initial setup)

    Usage:
        from adgn.props.prompt_improve.reminder_handler import ImprovementReminderHandler

        handler = ImprovementReminderHandler(
            improvement_run_id=run_id,
            type_config=type_config,
            db_config=db_config,
        )
        handlers = [handler, ...]
        agent = await Agent.create(..., handlers=handlers)
    """

    def __init__(
        self,
        improvement_run_id: UUID,
        type_config: ImprovementTypeConfig,
        db_config: DatabaseConfig,
        reminder_interval: int = 10,
    ):
        """Initialize handler.

        Args:
            improvement_run_id: The improvement agent's run ID
            type_config: ImprovementTypeConfig with baseline_definition_ids and allowed_examples
            db_config: Database configuration for creating sessions
            reminder_interval: Inject reminder every N turns after first 5 turns
        """
        self._improvement_run_id = improvement_run_id
        self._type_config = type_config
        self._db_config = db_config
        self._reminder_interval = reminder_interval
        self._turn_count = 0
        self._text_detected = False
        self._last_status: TerminationStatus | None = None

    def on_assistant_text_event(self, evt) -> None:
        """Track when assistant sends text (may need redirection)."""
        self._text_detected = True

    def on_before_sample(self) -> LoopDecision:
        """Check termination condition and inject reminder if needed."""
        self._turn_count += 1

        # Check termination condition
        with get_session() as session:
            status = check_termination_condition(
                session=session, improvement_run_id=self._improvement_run_id, type_config=self._type_config
            )

        self._last_status = status

        if status.should_terminate:
            logger.info(
                f"Improvement agent terminating: "
                f"definition '{status.best_candidate_id}' with {status.best_candidate_issues:.1f} issues "
                f"beats baseline avg {status.baseline_avg_issues:.1f}"
            )
            return Abort()

        # Inject reminder if:
        # 1. Text was detected (agent may be confused)
        # 2. Periodic interval (keep agent on track)
        should_remind = self._text_detected or (
            self._turn_count > 5 and self._turn_count % self._reminder_interval == 0
        )

        if should_remind and status.blocking_message:
            self._text_detected = False
            reminder = self._build_reminder(status)
            return InjectItems(items=[UserMessage.text(reminder)])

        self._text_detected = False
        return NoAction()

    def _build_reminder(self, status: TerminationStatus) -> str:
        """Build a reminder message from termination status."""
        lines = ["=== Improvement Agent Status ===", "", f"Blocking: {status.blocking_message}", ""]

        if status.baseline_avg_issues is not None:
            lines.append(f"Baseline average: {status.baseline_avg_issues:.1f} issues")

        if status.best_candidate_issues is not None:
            lines.append(f"Best candidate: {status.best_candidate_issues:.1f} issues ({status.best_candidate_id})")

        if status.missing_evals_count > 0:
            lines.append(f"Missing evals: {status.missing_evals_count}")

        lines.extend(
            [
                "",
                "Next steps:",
                "1. Query agent_runs to find your baseline_definition_ids and allowed_examples",
                "2. Run evals for any missing (definition, example) pairs",
                "3. Create improved definitions at /workspace/improved/ and call create_definition",
                "4. Keep iterating until your definition beats baseline average",
                "",
                "Do NOT send text messages asking for confirmation - execute your plan with tools.",
            ]
        )

        return "\n".join(lines)

    @property
    def last_status(self) -> TerminationStatus | None:
        """Get the last termination status check result."""
        return self._last_status
