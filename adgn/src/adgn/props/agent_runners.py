"""Shared agent runner helpers for critic and grader agents.

Extracts common patterns for running critic/grader agents to avoid duplication.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp.client import Client

from adgn.agent.agent import MiniCodex
from adgn.agent.handler import BaseHandler, Response
from adgn.agent.reducer import GateUntil
from adgn.agent.rich_display import RichDisplayHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp._shared.constants import GRADER_SUBMIT_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.compositor.setup import mount_standard_inproc_servers
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.cost import calculate_cost
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic import CriticSubmitPayload, CriticSubmitState, attach_critic_submit
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader import (
    CritiqueInputIssue,
    GradeInputs,
    GradeSubmitInput,
    GradeSubmitState,
    build_grader_submit_tools,
)
from adgn.props.ids import FalsePositiveID, InputIssueID, TruePositiveID
from adgn.props.lint_issue import BootstrapInspectHandler
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.specimens.registry import CanonicalIssue, IssueRecord, KnownFalsePositive, SpecimenRecord


class CostTrackingHandler(BaseHandler):
    """Handler that tracks total cost from Response events."""

    def __init__(self) -> None:
        self.total_cost: float = 0.0

    def on_response(self, evt: Response) -> None:
        """Accumulate cost from response usage."""
        self.total_cost += calculate_cost(evt.usage)


async def run_critic_agent(
    *,
    specimen_rec: SpecimenRecord,
    content_root: Path,
    system_prompt: str,
    user_prompt: str,
    client: OpenAIModelProto,
    transcript_dir: Path,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
) -> CriticSubmitPayload:
    """Run critic agent on a specimen with custom prompts.

    Args:
        specimen_rec: Specimen record (already loaded)
        content_root: Hydrated specimen root (caller manages lifecycle)
        system_prompt: System prompt for agent
        user_prompt: User prompt (scope description)
        client: OpenAI-compatible client
        transcript_dir: Where to write transcript
        mount_properties: Whether to mount /props (False for prompt eval, True for others)
        extra_handlers: Additional handlers (e.g., CostTrackingHandler, DisplayEventsHandler)

    Returns:
        CriticSubmitPayload on success

    Raises:
        RuntimeError if critic fails or errors
    """
    critic_state = CriticSubmitState()
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
        *extra_handlers,
    ]

    async with Client(comp) as mcp_client:
        # Mount standard servers (resources, compositor_meta, compositor_admin)
        await mount_standard_inproc_servers(compositor=comp)
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
        raise RuntimeError(f"Critic error: {critic_state.error.message}")

    if critic_state.result is None:
        raise RuntimeError("Critic did not submit")

    # Return result (caller persists to output.json)
    return critic_state.result


async def run_grader_agent(
    *,
    specimen_rec: SpecimenRecord,
    content_root: Path,
    critique: CriticSubmitPayload,
    canonical_issues: dict[str, IssueRecord] | None = None,
    known_fps: dict[str, IssueRecord] | None = None,
    scope_text: str,
    client: OpenAIModelProto,
    transcript_dir: Path,
    extra_handlers: tuple[BaseHandler, ...] = (),
    verbose: bool = False,
    verbose_prefix: str = "",
) -> GradeSubmitInput:
    """Run grader agent to match critique against canonical issues.

    Args:
        specimen_rec: Specimen record (already loaded)
        content_root: Hydrated specimen root (caller manages lifecycle)
        critique: Critique payload to grade
        canonical_issues: Optional override for canonical issues (uses specimen defaults if None)
        known_fps: Optional override for false positives (uses specimen defaults if None)
        scope_text: Description of analysis scope
        client: OpenAI-compatible client
        transcript_dir: Where to write transcript
        extra_handlers: Additional handlers (e.g., CostTrackingHandler) - excludes RichDisplayHandler
        verbose: If True, create RichDisplayHandler with proper server wiring
        verbose_prefix: Prefix for RichDisplayHandler output

    Returns:
        GradeSubmitInput on success

    Raises:
        RuntimeError if grader fails to submit
    """
    # Use specimen properties or convert provided dicts
    if canonical_issues is None:
        canonical_typed = specimen_rec.canonical_issues
    else:
        canonical_typed = [
            CanonicalIssue(
                id=TruePositiveID(record.core.id), rationale=record.core.rationale, occurrences=record.instances
            )
            for record in canonical_issues.values()
        ]

    if known_fps is None:
        fp_typed = specimen_rec.known_false_positives
    else:
        fp_typed = [
            KnownFalsePositive(
                id=FalsePositiveID(record.core.id), rationale=record.core.rationale, occurrences=record.instances
            )
            for record in known_fps.values()
        ]

    # Convert critique issues to CritiqueInputIssue
    critique_typed = [
        CritiqueInputIssue(id=InputIssueID(issue.id), rationale=issue.rationale, occurrences=issue.occurrences)
        for issue in critique.issues
    ]

    # Build grader inputs
    grader_state = GradeSubmitState()
    inputs = GradeInputs(specimen=specimen_rec, critique=critique)

    submit_tool_name = build_mcp_function("grader_submit", "submit_result")

    wiring = properties_docker_spec(content_root, mount_properties=True, ephemeral=False)
    prompt = build_grade_from_json_prompt(
        scope_text=scope_text,
        canonical_issues=canonical_typed,
        critique_issues=critique_typed,
        known_fps=fp_typed,
        submit_tool_name=submit_tool_name,
        wiring=wiring,
    )

    comp = Compositor("compositor")
    runtime_server = await wiring.attach(comp)
    grader_submit_server = NotifyingFastMCP(
        GRADER_SUBMIT_SERVER_NAME, instructions="Final grader submission for critique evaluation"
    )
    build_grader_submit_tools(grader_submit_server, grader_state, inputs=inputs)
    await comp.mount_inproc(GRADER_SUBMIT_SERVER_NAME, grader_submit_server)

    # Collect servers for RichDisplayHandler (if verbose)
    servers = {wiring.server_name: runtime_server, GRADER_SUBMIT_SERVER_NAME: grader_submit_server}

    handlers: list[BaseHandler] = [
        GateUntil(lambda: grader_state.result is not None),
        TranscriptHandler(dest_dir=transcript_dir),
    ]

    # Add verbose display if requested (with proper server wiring)
    if verbose:
        handlers.append(RichDisplayHandler(max_lines=10, prefix=verbose_prefix, servers=servers))

    # Add other handlers (e.g., cost tracking)
    handlers.extend(extra_handlers)

    async with Client(comp) as mcp_client:
        # Mount standard servers (resources, compositor_meta, compositor_admin)
        await mount_standard_inproc_servers(compositor=comp)
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

    # Return result (caller persists to output.json)
    return grader_state.result
