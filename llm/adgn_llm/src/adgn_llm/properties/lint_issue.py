from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import docker
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionToolCall
from importlib import resources as ilres

from adgn_llm.properties.prop_utils import properties_root, find_property_files
from adgn_llm.properties.specimen_utils import load_single_issue
from adgn_llm.mcp.docker_exec.server import (
    make_container_exec_mcp,
    SERVER_NAME as DOCKER_SERVER_NAME,
    TOOL_EXEC_NAME as DOCKER_EXEC_TOOL_NAME,
)
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mini_codex.loop_control import (
    Continue,
    Abort,
    RequireAny,
    SyntheticAction,
)
from adgn_llm.mini_codex.event_renderer import (
    ConsoleEventRenderer,
    DisplayEventsMixin,
)
from .specimen_utils import (
    ensure_archive_for_specimen_slug,
    Occurrence,
    LineRange,
)
from .prompt_utils import render_prompt_template
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

DOCKER_IMAGE = "adgn-llm/properties-critic:latest"


# ---------------------------------------------------------------------------
# Lint submit MCP server + shared state (accessible to controller and server)
# ---------------------------------------------------------------------------


class LintSubmitPayload(BaseModel):
    """Final linter result payload."""

    model_config = ConfigDict(extra="forbid")

    fail: bool = Field(
        ..., description="Set true if any property is violated; false if all checks pass."
    )
    message_md: str = Field(
        ..., description="Concise Markdown report; do not restate pass/fail."
    )
    corrected_anchors: dict[str, list[LineRange] | None] | None = Field(
        default=None,
        description=(
            "null or full replacement of Occurrence.files-style anchors: "
            "{path: [{start_line: int, end_line: int|null}] | null}"
        ),
    )


class LintSubmitState:
    done: bool = False
    result: LintSubmitPayload | None = None


def make_lint_submit_server(
    state: LintSubmitState, *, name: str = "lint_submit", occ: Occurrence
) -> FastMCP:
    """Tiny FastMCP server exposing a single tool: submit_result.

    The linter agent must call this exactly once to signal completion. This flips
    shared state so the loop controller will stop the run on the next sampling step.
    """
    mcp = FastMCP(name, instructions="Final result submission for linting run")

    @mcp.tool()
    async def submit_result(result: LintSubmitPayload) -> dict[str, Any]:
        """Submit final linter result."""
        state.result = result
        state.done = True
        return {"ok": True}

    return mcp


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


@dataclass
class LintConfig:
    specimen: str
    issue_id: str
    model: str = "gpt-5"
    dry_run: bool = False


def make_nl_tool_call(container_path: str, call_id: str) -> ResponseFunctionToolCall:
    """Create a docker exec tool call to render a file with line numbers.

    Reads the entire file (no size cap) using `nl -ba -w1 -s ' ' <path>`.
    """
    return ResponseFunctionToolCall(
        type="function_call",
        name=build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME),
        call_id=call_id,
        arguments=json.dumps({"cmd": ["nl", "-ba", "-w1", "-s", " ", container_path]}),
    )


def _build_prompt(
    issue: Any, property_md_files: list[Path], *, submit_tool_name: str, occurrence: Any
) -> str:
    # Do not include specimen slug or issue id. Include only issue fields.
    # The agent will read code from /workspace and property definitions from /props via MCP.
    issue_dict = issue.model_dump(exclude_none=True)
    issue_dict.pop("id", None)
    issue_dict["instances"] = [occurrence.model_dump(exclude_none=True)]
    issue_json = json.dumps(issue_dict, ensure_ascii=False)

    docker_tool_name = build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME)

    return render_prompt_template(
        "lint_issue.md.j2",
        issue_json=issue_json,
        docker_tool_name=docker_tool_name,
        submit_tool_name=submit_tool_name,
    )


# ---------------------------------------------------------------------------
# Deterministic bootstrap controller + always-require-tool policy + stop switch
# ---------------------------------------------------------------------------


BIG_THRESHOLD = 20480


# ---------------------------------------------------------------------------
# LinterController (purpose-specific) with integrated display + tool policy
# ---------------------------------------------------------------------------


class LinterController(DisplayEventsMixin):
    def __init__(
        self,
        *,
        state: LintSubmitState,
        occ: Occurrence,
        content_root: Path,
        prop_paths: list[str] | None = None,
        renderer: ConsoleEventRenderer | None = None,
    ) -> None:
        super().__init__(renderer=renderer, show_text=False)
        self._state = state
        self._step = 0
        # Snapshot specimen inputs
        self._files = list((occ.files or {}).keys())
        self._dirs = sorted({str(Path(p).parent) for p in self._files})
        # Determine sizes and big-file detection
        sizes: dict[str, int] = {}
        for p in self._files:
            hp = (content_root / p).resolve()
            st = hp.stat()
            if not hp.is_file():
                raise SystemExit(f"Expected a regular file for occurrence path: {hp}")
            sizes[p] = int(st.st_size)
        self._big_detected = any(size >= BIG_THRESHOLD for size in sizes.values())
        # Pre-build synthetic steps
        self._step1 = [
            ResponseFunctionToolCall(
                type="function_call",
                name="mcp__resources__read",
                call_id="bootstrap:res",
                arguments=json.dumps(
                    {
                        "server": "docker",
                        "uri": "resource://container.info",
                        "start_offset": 0,
                        "max_bytes": 65536,
                    }
                ),
            )
        ]
        if self._dirs:
            self._step2 = [
                ResponseFunctionToolCall(
                    type="function_call",
                    name=build_mcp_function(DOCKER_SERVER_NAME, DOCKER_EXEC_TOOL_NAME),
                    call_id="bootstrap:ls",
                    arguments=json.dumps(
                        {"cmd": ["ls", "-la"] + ["/workspace/" + d for d in self._dirs]}
                    ),
                )
            ]
        else:
            self._step2 = []

        def _content_calls() -> list[ResponseFunctionToolCall]:
            out: list[ResponseFunctionToolCall] = []
            for q in self._files:
                if sizes[q] > BIG_THRESHOLD:
                    continue
                out.append(
                    make_nl_tool_call(f"/workspace/{q}", f"bootstrap:show:{len(out) + 1}")
                )
            return out

        self._step3 = _content_calls()
        # Property definition reads (full files, no cap)
        self._prop_calls: list[ResponseFunctionToolCall] = []
        for i, p in enumerate(prop_paths or []):
            self._prop_calls.append(make_nl_tool_call(p, f"bootstrap:prop:{i + 1}"))

    def on_before_sample(self):  # type: ignore[override]
        # Stop immediately once submit_result was called
        if self._state.done:
            return Abort()
        # Bootstrap synthetic steps
        self._step += 1
        if self._step == 1:
            return SyntheticAction(outputs=self._step1)
        if self._step == 2 and self._step2:
            return SyntheticAction(outputs=self._step2)
        if self._step == 3 and self._files and not self._big_detected:
            return SyntheticAction(outputs=self._step3)
        if self._step == 4 and self._prop_calls:
            return SyntheticAction(outputs=self._prop_calls)
        # After bootstrap, always require a tool call until submit_result flips the switch
        return Continue(RequireAny())


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


async def run_specimen_lint_issue_async(
    specimen: str,
    issue_id: str,
    *,
    model: str = "gpt-5",
    dry_run: bool = False,
    gitconfig: str | None = None,
    occurrence_index: int,
    client: AsyncOpenAI,
) -> int:
    sp, root, issue = load_single_issue(specimen, issue_id, gitconfig)

    # Require a single occurrence; do not run on the full issue or mutate the Issue
    if occurrence_index < 0 or occurrence_index >= len(issue.instances):
        raise SystemExit(
            f"occurrence_index out of range: {occurrence_index} (instances={len(issue.instances)})",
        )
    occ = issue.instances[occurrence_index]

    # Always mount from under $HOME to avoid Docker volume restrictions on /var/folders
    ts = int(time.time())
    name = f"lint_{ts}"
    mount_root = (
        Path.home() / ".cache" / "adgn-llm" / "workspaces" / f"{specimen}_{name}"
    )
    mount_root.mkdir(parents=True, exist_ok=True)

    # Build submit tool name early (used in dry-run prompt too). Server is created later after hydration.
    submit_state = LintSubmitState()
    submit_tool_name = build_mcp_function("lint_submit", "submit_result")

    if dry_run:
        props = find_property_files([str(p) for p in issue.properties])
        prompt = _build_prompt(
            issue, props, submit_tool_name=submit_tool_name, occurrence=occ
        )
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        outfile = tmpdir / f"lint_issue_{issue_id}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        print(f"[dry-run] Saved prompt: {outfile}")
        return 0

    try:
        # Prepare mount directory under $HOME from cached archive; hard-fail if cache missing
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)
        archive = ensure_archive_for_specimen_slug(
            sp.manifest, sp.manifest_path, Path(gitconfig) if gitconfig else None
        )
        # Extract to mount_root
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(mount_root)

        # Determine content root: expect exactly one top-level directory after extraction
        entries = [p for p in mount_root.iterdir() if p.is_dir()]
        if len(entries) != 1:
            raise SystemExit(
                f"Unexpected archive layout under {mount_root}; expected a single top-level directory",
            )
        content_root = entries[0]

        # Ensure required critic image is available locally; guide user if missing (Docker SDK, no subprocess)
        try:
            dclient = docker.from_env()
            dclient.images.get(DOCKER_IMAGE)
        except docker.errors.ImageNotFound:
            build_hint = None

            pkg = "adgn_llm"
            dockerfile_trav = ilres.files(pkg).joinpath("docker/critic.Dockerfile")
            dockerfile_path = str(dockerfile_trav)
            # Use the parent dir of Dockerfile as context by default
            context_dir = str(dockerfile_trav.parent)
            build_hint = (
                f"docker build -f '{dockerfile_path}' -t {DOCKER_IMAGE} '{context_dir}'"
            )
            print("ERROR: Required Docker image not found:", DOCKER_IMAGE)
            if build_hint:
                print("Build it first:")
                print(build_hint)
            else:
                print(
                    "Please build the critic image (see docker/critic.Dockerfile) and retry."
                )
            return 2
        except Exception as e:
            print(f"ERROR: Docker daemon not reachable: {e}")
            return 2

        # Build in-process FastMCP servers: docker exec + submit server
        defs_dir = (properties_root() / "definitions").resolve()
        volumes = {
            str(content_root): {"bind": "/workspace", "mode": "ro"},
            str(defs_dir): {"bind": "/props", "mode": "ro"},
        }
        docker_spec = make_inproc_slot_spec(
            make_container_exec_mcp(
                image=DOCKER_IMAGE,
                working_dir="/workspace",
                volumes=volumes,
                describe=True,
            )
        )
        # Submit server needs occurrence for validation
        submit_server = make_lint_submit_server(submit_state, name="lint_submit", occ=occ)
        submit_spec = make_inproc_slot_spec(submit_server)

        specs = {"docker": docker_spec, "lint_submit": submit_spec}

        props = find_property_files([str(p) for p in issue.properties])
        # Map to container /props paths for mock reads
        prop_container_paths = [
            "/props/" + str(Path(p).resolve().relative_to(defs_dir).as_posix()) for p in props
        ]
        prompt = _build_prompt(
            issue, props, submit_tool_name=submit_tool_name, occurrence=occ
        )

        # Controller: single-purpose LinterController with display mixin; always require tool; stop when submitted
        ctrl = LinterController(
            state=submit_state,
            occ=occ,
            content_root=content_root,
            prop_paths=prop_container_paths,
            renderer=ConsoleEventRenderer(show_text=False),
        )

        async with McpManager(specs) as mcp:
            agent = await MiniCodex.create(
                model=model,
                mcp=mcp,
                system="You are a code agent. Be concise.",
                client=client,
            )
            result = await agent.run(prompt, controller=ctrl)
            text = result.text or ""

        # Print the exact occurrence representation as fed to the model
        issue_dict = issue.model_dump(exclude_none=True)
        issue_dict.pop("id", None)
        try:
            occ_dict = occ.model_dump(exclude_none=True)
        except Exception:
            occ_dict = occ  # fallback if already a dict-like
        issue_dict["instances"] = [occ_dict]
        issue_json = json.dumps(issue_dict, ensure_ascii=False)
        print("Issue (JSON):")
        print(issue_json)
        print()
        if submit_state.result and submit_state.result.message_md:
            print(submit_state.result.message_md)
            print()

        assert submit_state.done, "submit_result not called; should never happen."

        return 0 if (submit_state.result and submit_state.result.fail is False) else 2

    finally:
        # Cleanup copied workspace
        if mount_root.exists():
            shutil.rmtree(mount_root, ignore_errors=True)
