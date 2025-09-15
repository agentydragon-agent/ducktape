from __future__ import annotations

from typing import Any
import json
from pathlib import Path
import yaml

from openai import AsyncOpenAI

from adgn_llm.properties.specimens.registry import SpecimenRegistry
from adgn_llm.properties.docker_env import PropertiesDockerWiring
from adgn_llm.mini_codex.agent import MiniCodex
from adgn_llm.mini_codex.mcp_manager import McpManager, build_mcp_function
from adgn_llm.mini_codex.aggregating_handler import BaseHandler
from adgn_llm.mini_codex.loop_control import Continue, Abort, RequireAny
from adgn_llm.mcp.inproc_transport import make_inproc_slot_spec
from adgn_llm.properties.grader import (
    GradeSubmitState,
    make_grader_submit_server,
    GradeInputs,
    CANON_TP_PREFIX,
    CANON_FP_PREFIX,
    GradeSubmitPayload,
)
from adgn_llm.properties.prompts.builder import build_grade_from_json_prompt
from adgn_llm.properties.critic import ReportedIssue, CriticSubmitPayload
from adgn_llm.mini_codex.transcript_handler import TranscriptHandler
from adgn_llm.properties.grader import CRIT_PREFIX
from adgn_llm.mini_codex.loggers import TranscriptLoggerHandler


class _RequireSubmitHandler(BaseHandler):
    def __init__(self, state_obj: Any) -> None:
        self._state = state_obj

    def on_before_sample(self):  # type: ignore[override]
        if getattr(self._state, "result", None) is not None:
            return Abort()
        return Continue(RequireAny())


def _metrics_row(grade: GradeSubmitPayload, *, specimen: str | None = None) -> dict:
    m = grade.metrics
    row = m.model_dump()
    if specimen is not None:
        row["specimen"] = specimen
    row["fuzzy_precision"] = m.precision
    row["fuzzy_recall"] = m.recall
    return row


async def grade_critic_output(
    specimen: str,
    critic_obj: CriticSubmitPayload,
    client: AsyncOpenAI,
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
    canonical_ri = [ReportedIssue(core=it.core, occurrences=list(it.instances)) for it in rec.issues.values()]
    known_fp_ri = [
        ReportedIssue(core=it.core, occurrences=list(it.instances))
        for it in (getattr(rec, "false_positives", {}) or {}).values()
    ]

    # Prefix IDs for grading context clarity
    def _with_id_prefix(ri: ReportedIssue, prefix: str) -> dict:
        obj = ri.model_dump(exclude_none=True)
        core = obj.get("core", {})
        if core.get("id"):
            core["id"] = f"{prefix}{core['id']}"
        obj["core"] = core
        return obj

    canonical_json_list = [_with_id_prefix(ri, CANON_TP_PREFIX) for ri in canonical_ri]
    known_fp_json_list = [_with_id_prefix(ri, CANON_FP_PREFIX) for ri in known_fp_ri]

    # Critique (for prompt rendering and unknown YAML): build a dict copy with prefixed IDs
    critique_obj = json.loads(critic_obj.model_dump_json())
    issues = critique_obj.get("issues") or []
    for it in issues:
        core = it.get("core", {})
        if core.get("id") and not str(core["id"]).startswith(CRIT_PREFIX):
            core["id"] = f"{CRIT_PREFIX}{core['id']}"
        it["core"] = core
    critique_obj["issues"] = issues

    # Build allowed ID sets for validation and metrics counts
    allowed_critique_ids: set[str] = set()
    for it in critic_obj.issues:
        cid = it.core.id
        if cid:
            allowed_critique_ids.add(cid if str(cid).startswith(CRIT_PREFIX) else f"{CRIT_PREFIX}{cid}")

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
        canonical_json=json.dumps(canonical_json_list, ensure_ascii=False, indent=2),
        critique_json=json.dumps(critique_obj, ensure_ascii=False, indent=2),
        known_fp_json=json.dumps(known_fp_json_list, ensure_ascii=False, indent=2),
        submit_tool_name=submit_tool_name,
        wiring=wiring,
    )

    async with McpManager({"grader_submit": make_inproc_slot_spec(grader_server)}) as mcp:
        handlers: list[BaseHandler] = [
            _RequireSubmitHandler(grader_state),
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
        # Build quick index from critique by id
        crit_idx: dict[str, dict] = {}
        for it in critique_obj.get("issues", []):
            cid = it.get("core", {}).get("id")
            if isinstance(cid, str):
                crit_idx[cid] = it
        for cid in grader_state.result.unknown_critique_ids:
            it = crit_idx.get(cid)
            if not it:
                continue
            core = it.get("core", {})
            occs = it.get("occurrences", []) or []
            orig_id = str(core.get("id", "")).removeprefix(CRIT_PREFIX)
            for i, occ in enumerate(occs):
                data = {"core": core | {"id": orig_id}, "occurrence": occ}
                out = unk_dir / f"{orig_id}__occ{i}.yaml"
                out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    return grader_state.result
