from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adgn.llm.openai_utils.model import OpenAIModelProto
import yaml

from adgn.llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn.llm.mini_codex.agent import MiniCodex
from adgn.llm.mini_codex.aggregating_handler import BaseHandler, GateUntil
from adgn.llm.mini_codex.loggers import TranscriptLoggerHandler
from adgn.llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn.llm.mini_codex.transcript_handler import TranscriptHandler
from adgn.llm.properties.critic import CriticSubmitPayload, ReportedIssue
from adgn.llm.properties.docker_env import PropertiesDockerWiring
from adgn.llm.properties.grader import (
    CANON_FP_PREFIX,
    CANON_TP_PREFIX,
    CRIT_PREFIX,
    GradeInputs,
    GradeSubmitPayload,
    GradeSubmitState,
    make_grader_submit_server,
)
from adgn.llm.properties.prompts.builder import build_grade_from_json_prompt
from adgn.llm.properties.specimens.registry import SpecimenRegistry


def _metrics_row(
    grade: GradeSubmitPayload, *, specimen: str | None = None
) -> dict[str, Any]:
    m = grade.metrics
    row: dict[str, Any] = m.model_dump()
    if specimen is not None:
        row["specimen"] = specimen
    row["fuzzy_precision"] = m.precision
    row["fuzzy_recall"] = m.recall
    return row


async def grade_critic_output(
    specimen: str,
    critic_obj: CriticSubmitPayload,
    client: OpenAIModelProto,
    *,
    transcript_out_dir: Path,
):
    """Grade a critic output JSON for a specimen; return GradeSubmitPayload model.

    - Loads canonical positives and known false positives from SpecimenRegistry
    - Builds a grading prompt and runs MiniCodex with an in-proc grader_submit server
    - If transcript_out_dir is provided, writes JSONL transcript under transcript_out_dir/"grader"
    """
    rec = SpecimenRegistry.load_strict(specimen)

    # Build ReportedIssue objects to match the grader schema exactly
    canonical_ri = [
        ReportedIssue(
            id=it.core.id,
            rationale=it.core.rationale,
            occurrences=list(it.instances),
        )
        for it in rec.issues.values()
    ]
    known_fp_ri = [
        ReportedIssue(
            id=it.core.id,
            rationale=it.core.rationale,
            occurrences=list(it.instances),
        )
        for it in (getattr(rec, "false_positives", {}) or {}).values()
    ]

    # Prefix IDs for grading context clarity (typed)
    def _issue_with_id_prefix(ri: ReportedIssue, prefix: str) -> ReportedIssue:
        nid = ri.id
        new_id = f"{prefix}{nid}" if nid else nid
        return ReportedIssue(
            id=new_id, rationale=ri.rationale, occurrences=list(ri.occurrences)
        )

    canonical_prefixed = [
        _issue_with_id_prefix(ri, CANON_TP_PREFIX) for ri in canonical_ri
    ]
    known_fp_prefixed = [
        _issue_with_id_prefix(ri, CANON_FP_PREFIX) for ri in known_fp_ri
    ]

    # Critique (for prompt rendering and unknown YAML): build a typed copy with prefixed IDs
    critique_prefixed = CriticSubmitPayload.model_validate_json(
        critic_obj.model_dump_json()
    )
    new_issues: list[ReportedIssue] = []
    for it in critique_prefixed.issues:
        nid = it.id
        new_id = (
            f"{CRIT_PREFIX}{nid}"
            if nid and not str(nid).startswith(CRIT_PREFIX)
            else nid
        )
        new_issues.append(it.model_copy(update={"id": new_id}))
    critique_prefixed = critique_prefixed.model_copy(update={"issues": new_issues})

    # Build allowed ID sets for validation and metrics counts
    allowed_critique_ids: set[str] = set()
    for it in critic_obj.issues:
        cid = it.id
        if cid:
            allowed_critique_ids.add(
                cid if str(cid).startswith(CRIT_PREFIX) else f"{CRIT_PREFIX}{cid}",
            )

    grader_state = GradeSubmitState()
    # Build typed inputs for the grader server (specimen + critique payload)
    inputs = GradeInputs(specimen=rec, critique=critic_obj)
    grader_server = make_grader_submit_server(
        grader_state,
        name="grader_submit",
        inputs=inputs,
    )

    submit_tool_name = build_mcp_function("grader_submit", "submit_result")
    wiring = PropertiesDockerWiring(
        server_spec=None,  # type: ignore[arg-type]
        working_dir=Path("/"),
        definitions_container_dir=None,
        image_name="n/a",
    )

    prompt = build_grade_from_json_prompt(
        scope_text=f"Specimen: {specimen}",
        canonical_json=json.dumps(
            [ri.model_dump(exclude_none=True) for ri in canonical_prefixed],
            ensure_ascii=False,
            indent=2,
        ),
        critique_json=json.dumps(
            critique_prefixed.model_dump(exclude_none=True),
            ensure_ascii=False,
            indent=2,
        ),
        known_fp_json=json.dumps(
            [ri.model_dump(exclude_none=True) for ri in known_fp_prefixed],
            ensure_ascii=False,
            indent=2,
        ),
        submit_tool_name=submit_tool_name,
        wiring=wiring,
    )

    async with McpManager(
        {"grader_submit": make_inproc_slot_spec(grader_server)},
    ) as mcp:
        handlers: list[BaseHandler] = [
            GateUntil(lambda: grader_state.result is not None),
            TranscriptHandler(dest_dir=transcript_out_dir / "grader"),
            TranscriptLoggerHandler(transcript_out_dir / "grader"),
        ]
        # TODO(mpokorny): Expose grader model via CLI/caller; unify under
        # a typed AgentRecipe once the recipe system lands. For now this is
        # hardcoded and follows the default used across properties tools.
        agent = await MiniCodex.create(
            model="gpt-5",
            mcp=mcp,
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
            it = crit_idx.get(cid)
            if not it:
                continue
            orig_id = str(it.id or "").removeprefix(CRIT_PREFIX)
            for i, occ in enumerate(it.occurrences or []):
                core_dump = {"id": orig_id, "rationale": it.rationale}
                data = {
                    "core": core_dump,
                    "occurrence": occ.model_dump(exclude_none=True),
                }
                out = unk_dir / f"{orig_id}__occ{i}.yaml"
                out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return grader_state.result
