from __future__ import annotations

import pytest

from agent_core.testing.steps import AssertDockerExecThenCall, DockerExecCall, Step
from editor_agent.agent_runner import run_editor_docker_agent
from editor_agent.submit_server import SubmitStateSuccess


def _make_editor_steps(filename: str) -> list[Step]:
    """Step sequence: edit file in container, then submit."""
    return [
        # First call: edit the file
        DockerExecCall(cmd=["sh", "-c", f"echo 'modified content' > /workspace/{filename}"], timeout_ms=5000),
        # Second call: assert edit succeeded, then submit
        AssertDockerExecThenCall(
            expected_output="",
            next_cmd=["editor-submit", "submit-success", "--message", "done", "--file", f"/workspace/{filename}"],
            timeout_ms=5000,
        ),
    ]


@pytest.mark.requires_docker
async def test_editor_step_sequence(make_step_runner, tmp_path, async_docker_client, editor_image_id):
    """Test editor flow: init, edit file, submit-success, and writeback to host file."""
    fname = "file.txt"
    target = tmp_path / fname
    target.write_text("hello", encoding="utf-8")

    steps = _make_editor_steps(fname)
    runner = make_step_runner(steps=steps)

    result = await run_editor_docker_agent(
        file_path=target,
        prompt="test prompt",
        docker_client=async_docker_client,
        model_client=runner,
        max_turns=len(steps),
        image_id=editor_image_id,
    )

    # Verify success submission
    assert isinstance(result, SubmitStateSuccess)
    # Verify the modified content was written back to host
    assert target.read_text(encoding="utf-8") == "modified content\n"
