from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp.client import Client
import yaml

from adgn.agent.agent import MiniCodex
from adgn.agent.reducer import BaseHandler, GateUntil
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp._shared.constants import GRADER_SUBMIT_SERVER_NAME
from adgn.mcp._shared.naming import build_mcp_function
from adgn.mcp.compositor.server import Compositor
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.openai_utils.model import OpenAIModelProto
from adgn.props.critic import CriticSubmitPayload, ReportedIssue
from adgn.props.docker_env import properties_docker_spec
from adgn.props.grader import GradeInputs, GradeSubmitPayload, GradeSubmitState, build_grader_submit_tools
from adgn.props.ids import CANON_FP_PREFIX, CANON_TP_PREFIX, ensure_crit_id, ensure_with_prefix, strip_crit_prefix
from adgn.props.prompts.builder import build_grade_from_json_prompt
from adgn.props.specimens.registry import SpecimenRegistry


def _metrics_row(grade: GradeSubmitPayload, *, specimen: str | None = None) -> dict[str, Any]:
    m = grade.metrics
    row: dict[str, Any] = m.model_dump()
    if specimen is not None:
        row["specimen"] = specimen
    row["fuzzy_precision"] = m.precision
    row["fuzzy_recall"] = m.recall
    return row


async def grade_critic_output(
    specimen: str, critic_obj: CriticSubmitPayload, client: OpenAIModelProto, *, transcript_out_dir: Path
):
    """Grade a critic output JSON for a specimen; return GradeSubmitPayload model.

    - Loads canonical positives and known false positives from SpecimenRegistry
    - Builds a grading prompt and runs MiniCodex with an in-proc grader_submit server
    - If transcript_out_dir is provided, writes JSONL transcript under transcript_out_dir/"grader"
    """
    rec = SpecimenRegistry.load_strict(specimen)

    # Build ReportedIssue objects to match the grader schema exactly
    canonical_ri = [
        ReportedIssue(id=it.core.id, rationale=it.core.rationale, occurrences=list(it.instances))
        for it in rec.issues.values()
    ]
    known_fp_ri = [
        ReportedIssue(id=it.core.id, rationale=it.core.rationale, occurrences=list(it.instances))
        for it in rec.false_positives.values()
    ]

    # Prefix IDs for grading context clarity (typed)
    def _issue_with_id_prefix(ri: ReportedIssue, prefix: str) -> ReportedIssue:
        nid = ri.id
        new_id = ensure_with_prefix(nid, prefix)
        # Fallback to original id if ensure_with_prefix returns None (should not happen for valid inputs)
        rid = new_id if isinstance(new_id, str) else nid
        return ReportedIssue(id=rid, rationale=ri.rationale, occurrences=list(ri.occurrences))

    canonical_prefixed = [_issue_with_id_prefix(ri, CANON_TP_PREFIX) for ri in canonical_ri]
    known_fp_prefixed = [_issue_with_id_prefix(ri, CANON_FP_PREFIX) for ri in known_fp_ri]

    # Critique (for prompt rendering and unknown YAML): build a typed copy with prefixed IDs
    critique_prefixed = CriticSubmitPayload.model_validate_json(critic_obj.model_dump_json())
    new_issues: list[ReportedIssue] = []
    for it in critique_prefixed.issues:
        nid = it.id
        new_id = ensure_crit_id(nid)
        new_issues.append(it.model_copy(update={"id": new_id}))
    critique_prefixed = critique_prefixed.model_copy(update={"issues": new_issues})

    # Build allowed ID sets for validation and metrics counts
    allowed_critique_ids: set[str] = set()
    for it in critic_obj.issues:
        cid = ensure_crit_id(it.id)
        if cid:
            allowed_critique_ids.add(cid)

    grader_state = GradeSubmitState()
    # Build typed inputs for the grader server (specimen + critique payload)
    inputs = GradeInputs(specimen=rec, critique=critic_obj)

    submit_tool_name = build_mcp_function("grader_submit", "submit_result")
    # Use real wiring for prompt rendering (hydrate specimen and mount properties)
    async with rec.hydrated_copy(None) as content_root:
        wiring = properties_docker_spec(content_root, mount_properties=True, ephemeral=False)
        prompt = build_grade_from_json_prompt(
            scope_text=f"Specimen: {specimen}",
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
    # Build a small in-proc server and mount directly
    server = NotifyingFastMCP(
        GRADER_SUBMIT_SERVER_NAME, instructions="Final grader submission for specimen critique evaluation"
    )
    build_grader_submit_tools(server, grader_state, inputs=inputs)
    await comp.mount_inproc(GRADER_SUBMIT_SERVER_NAME, server)
    handlers: list[BaseHandler] = [
        GateUntil(lambda: grader_state.result is not None),
        # Canonical per-run transcript JSONL (events.jsonl + metadata.json)
        TranscriptHandler(dest_dir=transcript_out_dir / "grader"),
    ]
    async with Client(comp) as mcp_client:
        agent = await MiniCodex.create(
            model="gpt-5",
            mcp_client=mcp_client,
            system="You are a strict grader. Return only metrics via submit_result.",
            client=client,
            handlers=handlers,
            parallel_tool_calls=True,
        )
        await agent.run(prompt)

    assert grader_state.result, "grader_submit.submit_result was not called"

    # For unknown critique IDs, emit YAML files per occurrence under transcript_out_dir/unknowns
    if grader_state.result.unknown_critique_ids:
        unk_dir = Path(transcript_out_dir) / "unknowns"
        unk_dir.mkdir(parents=True, exist_ok=True)
        # Build quick index from critique by id (typed)
        crit_idx: dict[str, ReportedIssue] = {}
        for it in critique_prefixed.issues:
            if it.id:
                crit_idx[str(it.id)] = it
        for cid in grader_state.result.unknown_critique_ids:
            if not (pr_it := crit_idx.get(cid)):
                continue
            orig_id = strip_crit_prefix(str(pr_it.id or ""))
            for i, occ in enumerate(pr_it.occurrences):
                core_dump = {"id": orig_id, "rationale": pr_it.rationale}
                data = {"core": core_dump, "occurrence": occ.model_dump(exclude_none=True)}
                out = unk_dir / f"{orig_id}__occ{i}.yaml"
                out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return grader_state.result
