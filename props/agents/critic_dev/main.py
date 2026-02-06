"""Critic developer agent main entry point for in-container execution.

Shared entry point for both optimize and improve modes. The agent_type from
the agent_run's type_config determines which mode to use:
- PROMPT_OPTIMIZER: runs until budget/timeout exhaustion
- IMPROVEMENT: auto-terminates when a candidate beats baseline
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session
from sqlalchemy.types import String

from agent_core.agent import Agent
from agent_core.handler import AbortIf, BaseHandler, RedirectOnTextMessageHandler
from agent_core.loop_control import Abort, AllowAnyToolOrTextMessage, InjectItems, LoopDecision, NoAction
from openai_utils.model import SystemMessage, UserMessage
from props.agents.critic_dev.loop import (
    TEXT_OUTPUT_REMINDER,
    LoggingHandler,
    LoopState,
    LoopStatus,
    create_tool_provider,
)
from props.agents.eval_client import EvalClient
from props.agents.runtime import create_bound_model_from_env, get_current_agent_run, render_system_prompt, setup_logging
from props.core.agent_types import AgentType, ImprovementTypeConfig
from props.core.ids import DefinitionId
from props.core.models.examples import SingleFileSetExample
from props.db.config import DatabaseConfig
from props.db.database import Database

logger = logging.getLogger(__name__)


# =============================================================================
# Crane auth
# =============================================================================


def _setup_crane_auth(config: DatabaseConfig) -> None:
    """Write ~/.docker/config.json so crane can push/pull via Basic auth."""
    backend_url = os.environ.get("PROPS_BACKEND_URL")
    if not backend_url:
        raise RuntimeError("PROPS_BACKEND_URL must be set for crane auth setup")

    registry = urlparse(backend_url).netloc
    auth_token = base64.b64encode(f"{config.user}:{config.password}".encode()).decode()
    docker_config = {"auths": {registry: {"auth": auth_token}}}

    config_dir = Path.home() / ".docker"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps(docker_config))
    logger.info("Crane auth configured for registry %s", registry)


# =============================================================================
# Improvement mode: termination checking
# =============================================================================


class TerminationSuccess(BaseModel):
    kind: Literal["success"] = "success"
    definition_id: DefinitionId = Field(description="ID of the winning definition")
    total_credit: float = Field(description="Winning definition's sum of grader credits across allowed_examples")
    baseline_avg: float = Field(description="Average total_credit across baseline definitions")


class BlockingStatus(BaseModel):
    kind: Literal["blocking"] = "blocking"
    message: str = Field(description="Human-readable explanation of what's blocking termination")
    baseline_avg_issues: float | None = Field(
        default=None, description="Average total_credit across baseline definitions"
    )
    best_candidate_issues: float | None = Field(default=None, description="Best candidate's total_credit")
    best_candidate_id: str | None = Field(default=None, description="ID of the best candidate definition so far")
    missing_evals_count: int = Field(default=0, description="Number of (definition, example) pairs still needing evals")


TerminationResult = Annotated[TerminationSuccess | BlockingStatus, Field(discriminator="kind")]


def check_termination_condition(
    session: Session, improvement_run_id: UUID, type_config: ImprovementTypeConfig
) -> TerminationResult:
    baseline_ids = type_config.baseline_image_digests
    allowed_examples = type_config.allowed_examples
    n_examples = len(allowed_examples)

    baseline_query = text("""
        WITH allowed_examples AS (
            SELECT
                unnest(:snapshot_slugs) AS snapshot_slug,
                unnest(:example_kinds) AS example_kind,
                unnest(:files_hashes) AS files_hash
        ),
        baseline_issues AS (
            SELECT
                oc.critic_image_digest AS agent_definition_id,
                SUM(oc.found_credit) as total_issues
            FROM tp_occurrence_credits oc
            JOIN allowed_examples ae ON (
                oc.snapshot_slug = ae.snapshot_slug
                AND oc.example_kind::text = ae.example_kind
                AND COALESCE(oc.files_hash, '') = COALESCE(ae.files_hash, '')
            )
            WHERE oc.critic_image_digest = ANY(:baseline_ids)
            GROUP BY oc.critic_image_digest
        )
        SELECT AVG(total_issues) as avg_issues
        FROM baseline_issues
    """).bindparams(
        bindparam("baseline_ids", type_=ARRAY(String)),
        bindparam("snapshot_slugs", type_=ARRAY(String)),
        bindparam("example_kinds", type_=ARRAY(String)),
        bindparam("files_hashes", type_=ARRAY(String)),
    )

    snapshot_slugs = [str(ex.snapshot_slug) for ex in allowed_examples]
    example_kinds = [ex.kind for ex in allowed_examples]
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

    candidate_query = text("""
        WITH allowed_examples AS (
            SELECT
                unnest(:snapshot_slugs) AS snapshot_slug,
                unnest(:example_kinds) AS example_kind,
                unnest(:files_hashes) AS files_hash
        ),
        candidate_defs AS (
            SELECT digest as agent_definition_id
            FROM agent_definitions
            WHERE created_by_agent_run_id = :improvement_run_id
        ),
        candidate_coverage AS (
            SELECT
                cd.agent_definition_id,
                COUNT(DISTINCT (oc.snapshot_slug, oc.example_kind, COALESCE(oc.files_hash, ''))) as covered_examples,
                SUM(oc.found_credit) as total_issues
            FROM candidate_defs cd
            LEFT JOIN tp_occurrence_credits oc ON oc.critic_image_digest = cd.agent_definition_id
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

    best_candidate_id: str | None = None
    best_candidate_issues: float | None = None
    best_partial_candidate_id: str | None = None
    best_partial_issues: float | None = None
    best_partial_coverage: int = 0

    for row in candidate_results:
        covered = row.covered_examples or 0
        issues = row.total_issues or 0.0

        if covered >= n_examples:
            if best_candidate_issues is None or issues > best_candidate_issues:
                best_candidate_id = row.agent_definition_id
                best_candidate_issues = issues
        elif covered > best_partial_coverage or (
            covered == best_partial_coverage and (best_partial_issues is None or issues > best_partial_issues)
        ):
            best_partial_candidate_id = row.agent_definition_id
            best_partial_issues = issues
            best_partial_coverage = covered

    missing_baseline_query = text("""
        WITH required_examples AS (
            SELECT
                unnest(:snapshot_slugs) as snapshot_slug,
                unnest(:example_kinds) as example_kind,
                unnest(:files_hashes) as files_hash
        ),
        baseline_coverage AS (
            SELECT
                critic_image_digest AS agent_definition_id,
                snapshot_slug,
                example_kind,
                files_hash
            FROM tp_occurrence_credits
            WHERE critic_image_digest = ANY(:baseline_ids)
            GROUP BY critic_image_digest, snapshot_slug, example_kind, files_hash
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

    if best_candidate_id is not None and best_candidate_issues is not None:
        if baseline_avg is None:
            return BlockingStatus(
                message=(
                    f"Definition '{best_candidate_id}' has {best_candidate_issues:.1f} issues found, "
                    f"but baseline definitions have no evals yet. "
                    f"Run evals for {missing_baseline_evals} missing (baseline, example) pairs."
                ),
                best_candidate_issues=best_candidate_issues,
                best_candidate_id=best_candidate_id,
                missing_evals_count=missing_baseline_evals,
            )

        if best_candidate_issues > baseline_avg:
            return TerminationSuccess(
                definition_id=DefinitionId(best_candidate_id),
                total_credit=best_candidate_issues,
                baseline_avg=baseline_avg,
            )

        return BlockingStatus(
            message=(
                f"Definition '{best_candidate_id}' found {best_candidate_issues:.1f} issues, "
                f"but baseline average is {baseline_avg:.1f}. "
                f"Need to find more issues or create a better definition."
            ),
            baseline_avg_issues=baseline_avg,
            best_candidate_issues=best_candidate_issues,
            best_candidate_id=best_candidate_id,
        )

    if not candidate_results:
        return BlockingStatus(
            message=(
                "No definitions created yet. "
                "Create an improved definition at /workspace/improved/ and call create_definition."
            ),
            baseline_avg_issues=baseline_avg,
            missing_evals_count=missing_baseline_evals,
        )

    missing_examples = n_examples - best_partial_coverage
    return BlockingStatus(
        message=(
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
    def __init__(self, improvement_run_id: UUID, type_config: ImprovementTypeConfig, db: Database):
        if not type_config.baseline_image_digests:
            raise ValueError("baseline_image_digests must not be empty")
        if not type_config.allowed_examples:
            raise ValueError("allowed_examples must not be empty")

        self._improvement_run_id = improvement_run_id
        self._type_config = type_config
        self._db = db
        self._text_detected = False
        self._last_result: TerminationResult | None = None

    def on_assistant_text_event(self, evt) -> None:
        self._text_detected = True

    def on_before_sample(self) -> LoopDecision:
        with self._db.session() as session:
            result = check_termination_condition(
                session=session, improvement_run_id=self._improvement_run_id, type_config=self._type_config
            )

        self._last_result = result

        if isinstance(result, TerminationSuccess):
            logger.info(
                f"Critic developer terminating: "
                f"definition '{result.definition_id}' with {result.total_credit:.1f} issues "
                f"beats baseline avg {result.baseline_avg:.1f}"
            )
            return Abort()

        if self._text_detected:
            self._text_detected = False
            return InjectItems(items=[UserMessage.text(self._build_reminder(result))])

        return NoAction()

    def _build_reminder(self, status: BlockingStatus) -> str:
        lines = ["=== Critic Developer Status ===", "", f"Blocking: {status.message}", ""]

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
                "1. Create improved definition and call create_definition",
                "2. Run evals on your definition with run_critic",
                "3. Query recall views for grading results (handled by snapshot grader daemons)",
                "4. Iterate: refine definition, re-eval, until you beat baseline",
                "",
                "Do NOT send text messages - execute your plan with tools.",
            ]
        )

        return "\n".join(lines)

    @property
    def last_result(self) -> TerminationResult | None:
        return self._last_result


# =============================================================================
# Agent loop
# =============================================================================


async def run_agent_loop(
    system_prompt: str,
    eval_client: EvalClient,
    critic_model: str,
    db: Database,
    agent_type: AgentType,
    agent_run_id: UUID | None = None,
    type_config: ImprovementTypeConfig | None = None,
) -> int:
    """Run the critic developer agent loop.

    For optimize mode: runs until budget/timeout exhaustion.
    For improve mode: auto-terminates when a candidate beats baseline.
    """
    state = LoopState()
    tool_provider = create_tool_provider(state, eval_client, critic_model, db)
    bound_model = create_bound_model_from_env(db)

    # Common handlers for all modes
    handlers: list[BaseHandler] = [
        LoggingHandler(),
        RedirectOnTextMessageHandler(TEXT_OUTPUT_REMINDER),
        AbortIf(lambda: state.status != LoopStatus.IN_PROGRESS),
    ]

    # Type-specific handlers
    reminder_handler: ImprovementReminderHandler | None = None
    if agent_type == AgentType.IMPROVEMENT:
        assert agent_run_id is not None
        assert type_config is not None
        reminder_handler = ImprovementReminderHandler(improvement_run_id=agent_run_id, type_config=type_config, db=db)
        handlers.append(reminder_handler)

    agent = await Agent.create(
        tool_provider=tool_provider,
        handlers=handlers,
        client=bound_model,
        parallel_tool_calls=True,
        tool_policy=AllowAnyToolOrTextMessage(),
    )

    agent.process_message(SystemMessage.text(system_prompt))
    await agent.run()

    # Check improvement-specific termination (beat baseline)
    if reminder_handler is not None and isinstance(reminder_handler.last_result, TerminationSuccess):
        result = reminder_handler.last_result
        logger.info(
            "Critic developer succeeded: definition '%s' with %.1f issues beats baseline avg %.1f",
            result.definition_id,
            result.total_credit,
            result.baseline_avg,
        )
        return 0

    match state.status:
        case LoopStatus.EXITED_SUCCESS:
            logger.info("Critic developer reported success")
            return 0
        case LoopStatus.EXITED_FAILURE:
            logger.info("Critic developer failed")
            return 1
        case LoopStatus.IN_PROGRESS:
            if agent_type == AgentType.PROMPT_OPTIMIZER:
                # Ran until budget/timeout — that's success for optimize mode
                logger.info("Optimization completed (exhausted budget/turns)")
                return 0
            logger.warning("Agent finished without beating baseline")
            return 1


# =============================================================================
# Entry point
# =============================================================================


async def main() -> int:
    """Main entry point for critic developer agent."""
    setup_logging()

    db = Database.from_env()
    _setup_crane_auth(db.config)

    with db.session() as session:
        agent_run = get_current_agent_run(session)
        agent_run_id = agent_run.agent_run_id
        agent_type = agent_run.type_config.agent_type
        logger.info("Critic developer starting: %s mode, run=%s", agent_type.value, agent_run_id)

    improvement_config: ImprovementTypeConfig | None = None
    if agent_type == AgentType.PROMPT_OPTIMIZER:
        critic_model = agent_run.prompt_optimizer_config().critic_model
        mode = "optimize"
    elif agent_type == AgentType.IMPROVEMENT:
        improvement_config = agent_run.improvement_config()
        critic_model = improvement_config.critic_model
        mode = "improve"
    else:
        logger.error("Unexpected agent type: %s", agent_type)
        return 1

    async with EvalClient.from_env() as eval_client:
        system_prompt = render_system_prompt("props/agents/critic_dev/prompt.md.j2", db, helpers={"mode": mode})

        exit_code = await run_agent_loop(
            system_prompt=system_prompt,
            eval_client=eval_client,
            critic_model=critic_model,
            db=db,
            agent_type=agent_type,
            agent_run_id=agent_run_id if improvement_config else None,
            type_config=improvement_config,
        )

    logger.info("Agent loop finished with exit code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
