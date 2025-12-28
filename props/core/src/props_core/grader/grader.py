"""Grader agent environment and ORM conversion helpers.

Provides GraderAgentEnvironment for running grader agents. The actual execution
logic is in AgentRegistry.run_grader().
"""

from pathlib import Path
from uuid import UUID

import aiodocker
from fastmcp.server.auth import AuthProvider
from props_core.agent_setup import AgentEnvironment
from props_core.agent_workspace import WorkspaceManager
from props_core.db.agent_definition_ids import GRADER_AGENT_DEFINITION_ID
from props_core.db.config import DatabaseConfig
from props_core.display import short_uuid
from props_core.grader.models import FalsePositiveID, KnownFalsePositive, TruePositiveID, TruePositiveIssue
from props_core.grader.submit_server import GraderSubmitServer
from props_core.ids import SnapshotSlug
from props_core.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from props_core.rationale import Rationale

from mcp_infra.enhanced import EnhancedFastMCP


def _convert_files_jsonb(files_jsonb: dict) -> dict[Path, list[LineRange] | None]:
    result: dict[Path, list[LineRange] | None] = {}
    for path_str, ranges in files_jsonb.items():
        if ranges is None:
            result[Path(path_str)] = None
        else:
            # Each element is a dict with start_line/end_line
            result[Path(path_str)] = [LineRange(**r) for r in ranges]
    return result


def _tp_occ_from_orm(orm_occ) -> TruePositiveOccurrence:
    return TruePositiveOccurrence(
        occurrence_id=orm_occ.occurrence_id,
        files=_convert_files_jsonb(orm_occ.files),
        note=orm_occ.note,
        critic_scopes_expected_to_recall=orm_occ.critic_scopes_expected_to_recall_set,  # Already converts to set[frozenset[Path]]
    )


def _fp_occ_from_orm(orm_occ) -> FalsePositiveOccurrence:
    return FalsePositiveOccurrence(
        occurrence_id=orm_occ.occurrence_id,
        files=_convert_files_jsonb(orm_occ.files),
        note=orm_occ.note,
        relevant_files=orm_occ.relevant_files_set,  # Already converts to set[Path]
    )


def _tp_from_orm(orm_tp) -> TruePositiveIssue:
    return TruePositiveIssue(
        id=TruePositiveID(orm_tp.tp_id),
        rationale=Rationale(orm_tp.rationale),
        occurrences=[_tp_occ_from_orm(occ) for occ in orm_tp.occurrences],
    )


def _fp_from_orm(orm_fp) -> KnownFalsePositive:
    return KnownFalsePositive(
        id=FalsePositiveID(orm_fp.fp_id),
        rationale=Rationale(orm_fp.rationale),
        occurrences=[_fp_occ_from_orm(occ) for occ in orm_fp.occurrences],
    )


class GraderAgentEnvironment(AgentEnvironment):
    """Agent environment for SQL-based grader with grader_submit tool.

    Provides complete environment for grader agents:
    - Temporary database user with RLS scoping (grader_agent_{run_id})
    - HTTP MCP server with grader_submit tool
    - Docker container with docker_exec

    Snapshots are fetched by the agent at init time via fetch_snapshot() from
    props.agent_helpers. No bind mounts for snapshots.

    Agent workflow:
    1. Init script fetches snapshot to /snapshots/<slug>/
    2. Reads critique and ground truth from PostgreSQL via psql
    3. Writes grading decisions directly to PostgreSQL
    4. Calls grader_submit tool via MCP-over-HTTP when done
    5. Submit validates decisions and marks run complete

    Usage:
        async with GraderAgentEnvironment(
            snapshot_slug="ducktape/2025-11-26-00",
            docker_client=docker_client,
            grader_run_id=run_id,
            critic_run_id=critic_run_id,
        ) as compositor:
            # Run grader agent
            ...
    """

    def __init__(
        self,
        snapshot_slug: SnapshotSlug,
        docker_client: aiodocker.Docker,
        grader_run_id: UUID,
        critic_run_id: UUID,
        db_config: DatabaseConfig,
        workspace_manager: WorkspaceManager,
    ):
        # Store params needed by _make_mcp_server
        self._grader_run_id = grader_run_id
        self._critic_run_id = critic_run_id
        # Store snapshot_slug for reference (init script fetches it from DB)
        self._snapshot_slug = snapshot_slug

        super().__init__(
            definition_id=GRADER_AGENT_DEFINITION_ID,
            agent_run_id=grader_run_id,
            docker_client=docker_client,
            db_config=db_config,
            workspace_manager=workspace_manager,
            container_name=f"grader-{short_uuid(grader_run_id)}",
            labels={"adgn.project": "props", "adgn.role": "grader", "adgn.agent_run_id": str(grader_run_id)},
            auto_remove=True,
        )

    def _make_mcp_server(self, auth: AuthProvider) -> EnhancedFastMCP:
        return GraderSubmitServer(grader_run_id=self._grader_run_id, critic_run_id=self._critic_run_id, auth=auth)
