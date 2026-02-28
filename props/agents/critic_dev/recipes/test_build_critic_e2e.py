"""E2E test: mocked LLM agent invokes build_critic.sh.

Tests that build_critic.sh works when called via exec tool from a critic-dev
agent container. Uses the full orchestration stack (registry, backend,
FakeOpenAI) with mocked LLM responses.
"""

from __future__ import annotations

import logging
import textwrap

import pytest
import pytest_bazel
from hamcrest import assert_that

from agent_core.testing.responses import PlayGen
from mcp_infra.exec.matchers import exited_successfully
from props.agents.critic_dev.testing.mocks import CriticDevMock
from props.agents.critic_dev.testing.orchestration_fixtures import (
    ORCHESTRATION_CRITIC_MODEL,
    ORCHESTRATION_GRADER_MODEL,
    ORCHESTRATION_OPTIMIZER_MODEL,
)
from props.agents.grader.testing.mocks import GraderMock
from props.agents.grader.tools import ClusterMemberSpec
from props.core.agent_types import TargetMetric
from props.core.eval_api_models import CriticRunStatus, GradingStatusResponse, RunCriticRequest, StartCriticResponse
from props.core.ids import DefinitionId, SnapshotSlug
from props.core.models.examples import ExampleKind, WholeSnapshotExample
from props.db.models import AgentRun, AgentRunStatus, GradingEdge, ReportedIssue

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

# Custom main.py that writes a reported issue directly to DB (no LLM needed)
_CUSTOM_CRITIC_SCRIPT = textwrap.dedent("""\
    from __future__ import annotations

    import asyncio
    import sys

    from props.agents.runtime import get_current_agent_run_id
    from props.db.database import Database
    from props.db.models import ReportedIssue, ReportedIssueOccurrence
    from props.db.snapshots import LocationAnchor


    async def main() -> int:
        db = Database.from_env()

        with db.session() as session:
            agent_run_id = get_current_agent_run_id(session)
            print(f"Custom critic running as {agent_run_id}")

        with db.session() as session:
            agent_run_id = get_current_agent_run_id(session)
            issue = ReportedIssue(
                agent_run_id=agent_run_id,
                issue_id="build-script-test-issue",
                rationale="Test issue from build_critic.sh custom image",
            )
            session.add(issue)

        with db.session() as session:
            agent_run_id = get_current_agent_run_id(session)
            occ = ReportedIssueOccurrence(
                agent_run_id=agent_run_id,
                reported_issue_id="build-script-test-issue",
                locations=[LocationAnchor(file="test.py", start_line=1, end_line=5)],
            )
            session.add(occ)

        print("Custom critic completed: 1 issue, 1 occurrence")
        return 0


    if __name__ == "__main__":
        sys.exit(asyncio.run(main()))
""")


@pytest.mark.timeout(300)
@pytest.mark.slow
async def test_build_critic_sh_via_agent(
    synced_db, e2e_stack, test_snapshot, critic_dev_optimize_image, critic_image, grader_image
):
    """Verify build_critic.sh works when invoked by a mocked critic-dev agent.

    1. Writes a custom main.py to /workspace/
    2. Copies build_critic.sh into the container and invokes it
    3. Starts a critic with the resulting digest
    4. Verifies the custom image runs and produces a reported issue
    """
    snapshot_slug = SnapshotSlug(test_snapshot)

    @CriticDevMock.mock()
    def optimizer_mock(m: CriticDevMock) -> PlayGen:
        yield None  # First request

        # Write the custom critic script
        result = yield from m.exec_roundtrip(
            ["sh", "-c", f"cat > /workspace/custom_main.py << 'PYEOF'\n{_CUSTOM_CRITIC_SCRIPT}PYEOF"], timeout_ms=15000
        )
        assert_that(result, exited_successfully())

        # Write build_critic.sh into the container workspace
        # (In production, this would be at the runfiles path; for testing we
        # write it directly and set the needed env vars.)
        build_script = textwrap.dedent("""\
            #!/usr/bin/env bash
            set -euo pipefail

            CUSTOM_MAIN="${1:?Usage: build_critic.sh <path-to-custom-main.py> [variant-name]}"
            VARIANT="${2:-custom}"

            REGISTRY="${PROPS_REGISTRY_URL:?Set PROPS_REGISTRY_URL}"
            BASE_DIGEST="${PROPS_CRITIC_BASE_DIGEST:?Set PROPS_CRITIC_BASE_DIGEST}"

            WORK_DIR="$(mktemp -d)"
            trap 'rm -rf "$WORK_DIR"' EXIT

            BASE_REF="${REGISTRY}/critic@${BASE_DIGEST}"

            MAIN_PY_PATH="props/agents/critic/critic_bin.runfiles/_main/props/agents/critic/main.py"
            echo "Overlaying ${CUSTOM_MAIN} at ${MAIN_PY_PATH}" >&2

            mkdir -p "${WORK_DIR}/layer/${MAIN_PY_PATH%/*}"
            cp "${CUSTOM_MAIN}" "${WORK_DIR}/layer/${MAIN_PY_PATH}"
            tar -cf "${WORK_DIR}/layer.tar" -C "${WORK_DIR}/layer" .

            crane mutate "${BASE_REF}" \\
              --append "${WORK_DIR}/layer.tar" \\
              --tag "${REGISTRY}/critic:${VARIANT}" \\
              --output "${WORK_DIR}/image.tar" \\
              --insecure

            DIGEST="$(crane digest --tarball "${WORK_DIR}/image.tar")"

            crane push "${WORK_DIR}/image.tar" "${REGISTRY}/critic:${VARIANT}" --insecure

            echo "${DIGEST}"
        """)
        result = yield from m.exec_roundtrip(
            [
                "sh",
                "-c",
                f"cat > /workspace/build_critic.sh << 'SHEOF'\n{build_script}SHEOF\nchmod +x /workspace/build_critic.sh",
            ],
            timeout_ms=15000,
        )
        assert_that(result, exited_successfully())

        # Set up environment and invoke the build script
        build_cmd = (
            "REGISTRY=$(echo $PROPS_BACKEND_URL | sed 's|https\\?://||') && "
            "PROPS_REGISTRY_URL=$REGISTRY "
            "PROPS_CRITIC_BASE_DIGEST=$(crane digest $REGISTRY/critic:latest --insecure) "
            "bash /workspace/build_critic.sh /workspace/custom_main.py test-variant"
        )
        result = yield from m.exec_roundtrip(["sh", "-c", build_cmd], timeout_ms=120000)
        assert_that(result, exited_successfully())
        stdout = result.stdout if isinstance(result.stdout, str) else result.stdout.truncated_text
        new_digest = stdout.strip().split("\n")[-1]
        logger.info(f"build_critic.sh produced digest: {new_digest}")
        assert new_digest.startswith("sha256:"), f"Expected sha256 digest, got: {new_digest!r}"

        # Start the custom critic image
        example = WholeSnapshotExample(kind=ExampleKind.WHOLE_SNAPSHOT, snapshot_slug=snapshot_slug)
        start_output: StartCriticResponse = yield from m.start_critic_roundtrip(
            RunCriticRequest(
                definition_id=DefinitionId(new_digest),
                example=example,
                timeout_seconds=120,
                budget_usd=1.0,
                critic_model=ORCHESTRATION_CRITIC_MODEL,
            )
        )
        critic_run_id = start_output.critic_run_id
        logger.info(f"Custom critic run: {critic_run_id}")

        # Wait for critic to finish
        completed: CriticRunStatus = yield from m.wait_until_critic_completed_roundtrip(
            critic_run_id, timeout_seconds=120
        )
        logger.info(f"Critic completed: status={completed.status}")

        # Wait for grading
        wait_output: GradingStatusResponse = yield from m.wait_until_graded_roundtrip(critic_run_id, timeout_seconds=60)
        logger.info(f"Grading complete: total_credit={wait_output.total_credit}")

        yield m.report_success()

    @GraderMock.mock(check_consumed=False)
    def grader_mock(m: GraderMock) -> PlayGen:
        yield None  # First request

        drift = yield from m.get_drift_roundtrip()
        run_id = drift.grading[0].critique_run_id

        yield from m.fill_remaining_roundtrip(run_id, "build-script-test-issue", 4, "Mock: no GT matches")

        drift = yield from m.get_drift_roundtrip()
        assert len(drift.clustering) == 1

        yield from m.create_cluster_roundtrip(
            "novel-issues",
            "Unmatched issues from build_critic.sh test",
            [ClusterMemberSpec(run=run_id, issue_id="build-script-test-issue", rationale="Novel issue")],
        )

        yield from m.sleep_forever("All edges graded and clustered")

    mocks = {ORCHESTRATION_OPTIMIZER_MODEL: optimizer_mock, ORCHESTRATION_GRADER_MODEL: grader_mock}
    async with e2e_stack(mocks, images=[critic_dev_optimize_image, critic_image, grader_image]) as stack:
        grader_image_resolved = stack.resolved_images["grader"]
        opt_image = stack.resolved_images["critic_dev_optimize"]

        grader_handle = await stack.registry.start_snapshot_grader(
            image=grader_image_resolved, snapshot_slug=snapshot_slug, model=ORCHESTRATION_GRADER_MODEL
        )

        async with grader_handle:
            run_id = await stack.registry.run_critic_dev_optimize(
                image=opt_image,
                budget=1.0,
                optimizer_model=ORCHESTRATION_OPTIMIZER_MODEL,
                critic_model=ORCHESTRATION_CRITIC_MODEL,
                target_metric=TargetMetric.WHOLE_REPO,
                timeout_seconds=180,
            )

            with synced_db.session() as session:
                optimizer_run = session.get(AgentRun, run_id)
                assert optimizer_run is not None
                assert optimizer_run.status == AgentRunStatus.EXITED

                # Verify the build_critic.sh-produced image created the expected issue
                issues = session.query(ReportedIssue).filter_by(issue_id="build-script-test-issue").all()
                assert len(issues) == 1, f"Expected 1 issue from build_critic.sh, got {len(issues)}"

                # Verify grading edges were created
                critic_run_id = issues[0].agent_run_id
                edges = session.query(GradingEdge).filter_by(critique_run_id=critic_run_id).all()
                assert len(edges) > 0, "Expected grading edges for the build_critic.sh-produced critic run"


if __name__ == "__main__":
    pytest_bazel.main()
