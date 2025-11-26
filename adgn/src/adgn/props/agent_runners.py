"""Shared agent runner helpers for critic and grader agents.

Extracts common patterns for running critic/grader agents to avoid duplication.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastmcp.client import Client

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler, Response
from adgn.agent.reducer import GateUntil
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp._shared.constants import GRADER_SUBMIT_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.cost import calculate_cost
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic import CriticSubmitPayload, CriticSubmitState, ReportedIssue, attach_critic_submit
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader import GradeInputs, GradeSubmitPayload, GradeSubmitState, build_grader_submit_tools
from adgn.props.ids import CANON_FP_PREFIX, CANON_TP_PREFIX, ensure_crit_id, ensure_with_prefix
from adgn.props.lint_issue import BootstrapInspectHandler
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.specimens.registry import IssueRecord, SpecimenRecord


class CostTrackingHandler(BaseHandler):
    """Handler that tracks total cost from Response events."""

    def __init__(self) -> None:
        self.total_cost: float = 0.0

    def on_response(self, evt: Response) -> None:
        """Accumulate cost from response usage."""
        self.total_cost += calculate_cost(evt.usage)


def _prefix_critique_ids(critique: CriticSubmitPayload) -> CriticSubmitPayload:
    """Prefix all critique issue IDs with crit_ for grading.

    Returns a new CriticSubmitPayload with prefixed IDs.
    """
    critique_prefixed = CriticSubmitPayload.model_validate_json(critique.model_dump_json())
    new_issues: list[ReportedIssue] = []
    for it in critique_prefixed.issues:
        nid = it.id
        new_id = ensure_crit_id(nid)
        new_issues.append(it.model_copy(update={"id": new_id}))
    return critique_prefixed.model_copy(update={"issues": new_issues})


def _issue_with_id_prefix(ri: ReportedIssue, prefix: str) -> ReportedIssue:
    """Add a prefix to an issue ID (shared helper for grading)."""
    nid = ri.id
    new_id = ensure_with_prefix(nid, prefix)
    rid = new_id if isinstance(new_id, str) else nid
    return ReportedIssue(id=rid, rationale=ri.rationale, occurrences=list(ri.occurrences))


def _build_canonical_issues(
    issues: dict[str, IssueRecord], false_positives: dict[str, IssueRecord] | None = None
) -> tuple[list[ReportedIssue], list[ReportedIssue]]:
    """Build prefixed canonical positive and false positive issue lists.

    Returns:
        (canonical_positives_prefixed, known_fps_prefixed)
    """
    canonical_ri = [
        ReportedIssue(id=it.core.id, rationale=it.core.rationale, occurrences=list(it.instances))
        for it in issues.values()
    ]

    known_fp_ri: list[ReportedIssue] = []
    if false_positives:
        known_fp_ri = [
            ReportedIssue(id=it.core.id, rationale=it.core.rationale, occurrences=list(it.instances))
            for it in false_positives.values()
        ]

    canonical_prefixed = [_issue_with_id_prefix(ri, CANON_TP_PREFIX) for ri in canonical_ri]
    known_fp_prefixed = [_issue_with_id_prefix(ri, CANON_FP_PREFIX) for ri in known_fp_ri]

    return canonical_prefixed, known_fp_prefixed


async def run_critic_agent(
    *,
    specimen_rec: SpecimenRecord,
    system_prompt: str,
    user_prompt: str,
    client: OpenAIModelProto,
    transcript_dir: Path,
    mount_properties: bool = False,
    gitconfig: Path | None = None,
    extra_handlers: tuple[BaseHandler, ...] = (),
) -> CriticSubmitPayload:
    """Run critic agent on a specimen with custom prompts.

    Args:
        specimen_rec: Specimen record (already loaded)
        system_prompt: System prompt for agent
        user_prompt: User prompt (scope description)
        client: OpenAI-compatible client
        transcript_dir: Where to write transcript
        mount_properties: Whether to mount /props (False for prompt eval, True for others)
        gitconfig: Optional gitconfig for private repos
        extra_handlers: Additional handlers (e.g., CostTrackingHandler, DisplayEventsHandler)

    Returns:
        CriticSubmitPayload on success

    Raises:
        RuntimeError if critic fails or errors
    """
    critic_state = CriticSubmitState()

    async with specimen_rec.hydrated_copy(gitconfig) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=mount_properties)
        comp = Compositor("compositor")
        await wiring.attach(comp)
        await attach_critic_submit(comp, critic_state)

        bootstrap = BootstrapInspectHandler(wiring)

        def _ready_state() -> bool:
            return (critic_state.result is not None) or (critic_state.error is not None)

        def _defer_bootstrap() -> bool:
            return not bootstrap._done

        handlers: list[BaseHandler] = [
            bootstrap,
            TranscriptHandler(dest_dir=transcript_dir),
            GateUntil(_ready_state, defer_when=_defer_bootstrap),
        ]
        handlers.extend(extra_handlers)

        async with Client(comp) as mcp_client:
            # Mount standard servers (resources, compositor_meta, compositor_admin)
            # Must be done after creating the client so resources server has gateway access
            await mount_standard_inproc_servers(compositor=comp, gateway_client=mcp_client)
            agent = await MiniCodex.create(
                model=client.model,
                mcp_client=mcp_client,
                system=system_prompt,
                client=client,
                handlers=handlers,
                parallel_tool_calls=True,
            )
            await agent.run(user_prompt)

    # Check result
    if critic_state.error is not None:
        (transcript_dir.parent / "critic_error.json").write_text(
            critic_state.error.model_dump_json(indent=2), encoding="utf-8"
        )
        raise RuntimeError(f"Critic error: {critic_state.error.message}")

    if critic_state.result is None:
        raise RuntimeError("Critic did not submit")

    # Persist successful critique
    (transcript_dir.parent / "critique.json").write_text(
        critic_state.result.model_dump_json(indent=2), encoding="utf-8"
    )
    return critic_state.result


async def run_grader_agent(
    *,
    specimen_rec: SpecimenRecord,
    critique: CriticSubmitPayload,
    canonical_issues: dict[str, IssueRecord] | None = None,
    known_fps: dict[str, IssueRecord] | None = None,
    scope_text: str,
    client: OpenAIModelProto,
    transcript_dir: Path,
    gitconfig: Path | None = None,
    extra_handlers: tuple[BaseHandler, ...] = (),
) -> GradeSubmitPayload:
    """Run grader agent to match critique against canonical issues.

    Args:
        specimen_rec: Specimen record (for wiring and validation context)
        critique: Critique payload to grade
        canonical_issues: Canonical positive issues to match against (None = use all from specimen_rec)
        known_fps: Known false positives (None = use all from specimen_rec)
        scope_text: Scope description for prompt
        client: OpenAI-compatible client
        transcript_dir: Where to write transcript
        gitconfig: Optional gitconfig for private repos
        extra_handlers: Additional handlers (e.g., CostTrackingHandler, DisplayEventsHandler)

    Returns:
        GradeSubmitPayload on success

    Raises:
        RuntimeError if grader fails
    """
    # Use provided issues or default to full specimen
    issues_to_grade = canonical_issues if canonical_issues is not None else specimen_rec.issues
    fps_to_grade = known_fps if known_fps is not None else (specimen_rec.false_positives or {})

    # Build prefixed canonical and FP lists
    canonical_prefixed, known_fp_prefixed = _build_canonical_issues(issues_to_grade, fps_to_grade)

    # Prefix critique IDs
    critique_prefixed = _prefix_critique_ids(critique)

    # Build grader inputs (uses full specimen for validation context)
    grader_state = GradeSubmitState()
    inputs = GradeInputs(specimen=specimen_rec, critique=critique)

    submit_tool_name = build_mcp_function("grader_submit", "submit_result")

    async with specimen_rec.hydrated_copy(gitconfig) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=True, ephemeral=False)
        prompt = build_grade_from_json_prompt(
            scope_text=scope_text,
            canonical_json=json.dumps(
                [ri.model_dump(exclude_none=True) for ri in canonical_prefixed], ensure_ascii=False, indent=2
            ),
            critique_json=json.dumps(critique_prefixed.model_dump(exclude_none=True), ensure_ascii=False, indent=2),
            known_fp_json=json.dumps(
                [ri.model_dump(exclude_none=True) for ri in known_fp_prefixed], ensure_ascii=False, indent=2
            ),
            submit_tool_name=submit_tool_name,
            wiring=wiring,
        )

    comp = Compositor("compositor")
    server = NotifyingFastMCP(GRADER_SUBMIT_SERVER_NAME, instructions="Final grader submission for critique evaluation")
    build_grader_submit_tools(server, grader_state, inputs=inputs)
    await comp.mount_inproc(GRADER_SUBMIT_SERVER_NAME, server)

    handlers: list[BaseHandler] = [
        GateUntil(lambda: grader_state.result is not None),
        TranscriptHandler(dest_dir=transcript_dir),
    ]
    handlers.extend(extra_handlers)

    async with Client(comp) as mcp_client:
        # Mount standard servers (resources, compositor_meta, compositor_admin)
        await mount_standard_inproc_servers(compositor=comp, gateway_client=mcp_client)
        agent = await MiniCodex.create(
            model="gpt-5",
            mcp_client=mcp_client,
            system="You are a strict grader. Return only metrics via submit_result.",
            client=client,
            handlers=handlers,
            parallel_tool_calls=True,
        )
        await agent.run(prompt)

    if grader_state.result is None:
        raise RuntimeError("Grader did not submit")

    # Persist grade
    (transcript_dir.parent / "grade.json").write_text(grader_state.result.model_dump_json(indent=2), encoding="utf-8")
    return grader_state.result
