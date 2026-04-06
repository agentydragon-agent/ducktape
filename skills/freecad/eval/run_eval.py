"""Run a FreeCAD skill eval: agent produces baseplate.FCStd, transcript logged.

Usage:
  ANTHROPIC_API_KEY=sk-... bazel run //skills/freecad/eval:run_eval -- /tmp/eval-output
  ANTHROPIC_API_KEY=sk-... bazel run //skills/freecad/eval:run_eval -- /tmp/out --model claude-opus-4-6
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, SystemMessage, query

from mcp_infra.exec.docker.types import AlwaysSetTo, BindMount, ContainerExecServerConfig
from util.bazel.runfiles import get_required_path
from util.oci import OciImage, load_oci_image

logger = logging.getLogger(__name__)

FREECAD_TEST = OciImage("_main/skills/freecad/eval/freecad_test.rloc", "freecad-test:pinned")
TASK_MD = "_main/skills/freecad/eval/baseplate/TASK.md"
DOCKER_LAUNCHER = "_main/mcp_infra/exec/docker_launcher"
SKILL_DIR = "_main/skills/freecad"

SKILL_CONTAINER_DIR = "/skill"

SYSTEM_PROMPT = f"""\
You are working inside a FreeCAD Docker container via the exec and read_image MCP tools.

The FreeCAD skill (SKILL.md) and all example scripts are at {SKILL_CONTAINER_DIR}/.
Read {SKILL_CONTAINER_DIR}/SKILL.md before starting — it contains essential FreeCAD
scripting patterns, constraints, and gotchas. The example scripts (parametric_sketch.py,
build_compound.py, etc.) are reference implementations you can study.

Your working directory is /workspace. Save all output files there.

FreeCAD is available as `freecadcmd`. Use `xvfb-run -a -s "-screen 0 1024x768x24" freecadcmd`
for any script that needs GUI/TechDraw rendering.

Use the read_image tool to visually inspect PNG/SVG outputs you produce.
"""


async def run(output_dir: Path, model: str) -> None:
    logger.info("Loading FreeCAD Docker image")
    tag = load_oci_image(FREECAD_TEST)
    logger.info("Image loaded: %s", tag)

    workspace = output_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Copy skill files to a host directory that will be bind-mounted
    # into the container at SKILL_CONTAINER_DIR (read-only).
    skill_src_dir = get_required_path(SKILL_DIR)
    skill_host_dir = output_dir / "skill"
    skill_host_dir.mkdir(parents=True, exist_ok=True)
    for src in skill_src_dir.iterdir():
        if src.is_file():
            shutil.copy2(src, skill_host_dir / src.name)
    logger.info("Skill files staged at %s", skill_host_dir)

    # Read SKILL.md to include in the first user message
    skill_md = (skill_host_dir / "SKILL.md").read_text()
    task_text = get_required_path(TASK_MD).read_text()
    user_prompt = f"{skill_md}\n\n---\n\n{task_text}"

    launcher_binary = str(get_required_path(DOCKER_LAUNCHER))

    config = ContainerExecServerConfig(
        image=tag,
        working_dir=Path("/workspace"),
        binds=[
            BindMount(host_path=workspace, container_path=Path("/workspace")),
            BindMount(host_path=skill_host_dir, container_path=Path(SKILL_CONTAINER_DIR), mode="ro"),
        ],
        allow_user_field=False,
        allow_env_field=False,
        cwd_policy=AlwaysSetTo(value=Path("/workspace")),
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as config_file:
        config_file.write(config.model_dump_json())
        config_path = config_file.name

    transcript_path = output_dir / "transcript.jsonl"
    start = time.monotonic()
    session_id: str | None = None
    cost_usd = 0.0
    turn_count = 0

    with transcript_path.open("a") as log_f:
        async for message in query(
            prompt=user_prompt,
            options=ClaudeAgentOptions(
                cwd=str(workspace),
                allowed_tools=["mcp__freecad__*"],
                mcp_servers={"freecad": {"command": launcher_binary, "args": [config_path]}},
                permission_mode="bypassPermissions",
                max_turns=200,
                model=model,
                system_prompt=SYSTEM_PROMPT,
            ),
        ):
            entry = dataclasses.asdict(message)
            entry["_type"] = type(message).__name__
            entry["_timestamp"] = time.time()

            if isinstance(message, AssistantMessage):
                turn_count += 1
            elif isinstance(message, ResultMessage):
                cost_usd = float(message.total_cost_usd or 0)
                logger.info("Result: stop_reason=%s, cost=$%.4f, turns=%d", message.stop_reason, cost_usd, turn_count)
            elif isinstance(message, SystemMessage) and message.subtype == "init":
                session_id = message.data.get("session_id")
                logger.info("Session: %s", session_id)

            log_f.write(json.dumps(entry, default=str) + "\n")
            log_f.flush()

    duration = time.monotonic() - start

    metadata = {
        "model": model,
        "cost_usd": cost_usd,
        "duration_s": round(duration, 1),
        "turns": turn_count,
        "session_id": session_id,
        "task": "baseplate",
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    artifacts = sorted(str(p.relative_to(workspace)) for p in workspace.rglob("*") if p.is_file())
    logger.info("Done. %d turns, $%.4f, %.0fs", turn_count, cost_usd, duration)
    logger.info("Artifacts: %s", artifacts)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Run FreeCAD skill evaluation")
    parser.add_argument("output_dir", type=Path, help="Directory for eval outputs")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Model to use")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.output_dir, args.model))


if __name__ == "__main__":
    main()
