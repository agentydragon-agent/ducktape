"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.llm.rendering.rich_renderers import render_to_rich
from adgn.mcp._shared.types import SimpleOk
from adgn.mcp.notifying_fastmcp import NotifyingFastMCP
from adgn.props.critic import CriticSubmitPayload
from adgn.props.ids import CANON_FP_PREFIX, CANON_TP_PREFIX, ensure_crit_id, ensure_with_prefix
from adgn.props.specimens.registry import IssueRecord, SpecimenRecord

# Shared ID prefix constants (single source of truth) live in adgn.props.ids


class GradeMetrics(BaseModel):
    """Basic grading metrics (no per-property breakdown)."""

    expected: int = Field(..., description="Number of canonical items (ground truth)")
    reported: int = Field(..., description="Number of items reported by critique")
    true_positives: int = Field(..., description="Reported items that match canonical")
    false_positive: int = Field(..., description="Reported items known to be false positives (in known-FP list)")
    unknown: int = Field(..., description="Reported items neither in canonical positives nor in known false positives")
    false_negatives: int = Field(..., description="Canonical items missing in report")
    precision: float = Field(..., description="TP / (TP + false_positive + unknown); 0.0 if undefined")
    recall: float = Field(..., description="TP / expected (known-positives); 0.0 if undefined")
    # Fractional coverage-based recall in [0,1], computed from coverage credits when expected>0
    coverage_recall: float | None = Field(
        default=None,
        description=(
            "Fractional recall in [0,1] derived from per-canonical coverage credits "
            "(sum of credits per canonical clamped to 1.0, averaged over expected)."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class GradeSubmitInput(BaseModel):
    """Submission object expected from the grader.

    Return categorized IDs (source-validated) and smart precision/recall floats:
    - true_positive_ids, false_positive_ids: MUST be canonical IDs only (canon_tp_ or canon_fp_)
    - unknown_critique_ids: MUST be critique IDs only (crit_)
    - precision, recall: floats in [0.0, 1.0] reflecting weighted/smart matching (issue importance, occurrence coverage)
    """

    true_positive_ids: list[str] = Field(default_factory=list)
    false_positive_ids: list[str] = Field(default_factory=list)
    unknown_critique_ids: list[str] = Field(default_factory=list)
    precision: float = Field(..., ge=0.0, le=1.0, description="LLM-assessed precision in [0,1] (smart-weighted)")
    recall: float = Field(..., ge=0.0, le=1.0, description="LLM-assessed recall in [0,1] (smart-weighted)")
    message_md: str | None = Field(
        default=None, description="Optional Markdown summary/notes; may include tables of examples"
    )

    # REQUIRED fractional coverage credits attributed per critique issue.
    # Each entry assigns a fraction of credit [0,1] from a critique item to a canonical positive.
    # The grader server aggregates across critique items, clamps per-canonical totals to 1.0,
    # and computes coverage_recall accordingly.
    coverage_credits: list[CoverageCredit] = Field(
        ..., description="Per-critique fractional credits toward canonical positives"
    )

    @model_validator(mode="after")
    def _validate_coverage_totals(self) -> GradeSubmitInput:
        """Ensure total credit per canonical does not exceed 1.0.

        Credits are already constrained to [0,1] individually; this aggregates by
        canonical id and enforces totals ≤ 1.0 (with a small epsilon for FP rounding).
        """
        totals: dict[str, float] = {}
        for c in self.coverage_credits:
            totals[c.canon_id] = totals.get(c.canon_id, 0.0) + float(c.credit)
        # Allow tiny FP tolerance
        bad = {k: v for k, v in totals.items() if v > 1.0 + 1e-6}
        if bad:
            raise ValueError(f"coverage_credits total exceeds 1.0 for canonical ids: {bad}")
        return self

    model_config = ConfigDict(extra="forbid")


class GradeSubmitPayload(BaseModel):
    """Final grader output persisted by the host: metrics + optional writeup + IDs."""

    metrics: GradeMetrics
    true_positive_ids: list[str] = Field(default_factory=list)
    false_positive_ids: list[str] = Field(default_factory=list)
    unknown_critique_ids: list[str] = Field(default_factory=list)
    message_md: str | None = Field(
        default=None, description="Optional Markdown summary/notes; may include tables of examples"
    )

    model_config = ConfigDict(extra="forbid")


class GradeSubmitState:
    """Container for submitted GradeSubmitPayload."""

    result: GradeSubmitPayload | None = None


@dataclass(frozen=True)
class GradeInputs:
    """Single cohesive context for grading: specimen and the critique payload."""

    specimen: SpecimenRecord
    critique: CriticSubmitPayload
    round: int | None = None


def build_grader_submit_tools(mcp: NotifyingFastMCP, state: GradeSubmitState, *, inputs: GradeInputs) -> None:
    """Register grader submit tool on an existing server (tools-builder pattern)."""
    # Derive allowed ID sets and counts from specimen and critique

    def _prefixed_ids(items: Iterable[IssueRecord], prefix: str) -> set[str]:
        out: set[str] = set()
        for rec in items:
            cid = rec.core.id
            if cid:
                norm = ensure_with_prefix(cid, prefix)
                if norm:
                    out.add(norm)
        return out

    allowed_canon_ids: set[str] = _prefixed_ids(inputs.specimen.issues.values(), CANON_TP_PREFIX)
    if inputs.specimen.false_positives:
        allowed_canon_ids |= _prefixed_ids(inputs.specimen.false_positives.values(), CANON_FP_PREFIX)

    # Only true positives are eligible for fractional coverage credit
    allowed_tp_ids: set[str] = _prefixed_ids(inputs.specimen.issues.values(), CANON_TP_PREFIX)

    allowed_critique_ids: set[str] = set()
    for it in inputs.critique.issues:
        cid = ensure_crit_id(it.id)
        if cid:
            allowed_critique_ids.add(cid)

    expected_count = len(inputs.specimen.issues)
    reported_count = len(inputs.critique.issues)

    @mcp.flat_model()
    async def submit_result(result: GradeSubmitInput) -> SimpleOk:
        """Submit the final grading result (IDs only)."""
        # Optional validation of ID sets
        if allowed_canon_ids is not None:
            bad_tp = [i for i in result.true_positive_ids if i not in allowed_canon_ids]
            bad_fp = [i for i in result.false_positive_ids if i not in allowed_canon_ids]
            if bad_tp or bad_fp:
                raise ValueError(f"grader returned non-canonical IDs: tp={bad_tp} fp={bad_fp}")
        if allowed_critique_ids is not None:
            bad_unk = [i for i in result.unknown_critique_ids if i not in allowed_critique_ids]
            if bad_unk:
                raise ValueError(f"grader returned non-critique IDs in unknown_critique_ids: {bad_unk}")
        # Compute deterministic counts from ID lists; use grader-provided precision/recall
        tp = len(result.true_positive_ids)
        fp = len(result.false_positive_ids)
        unk = len(result.unknown_critique_ids)
        exp = expected_count or 0
        rep = reported_count or 0
        fn = max(0, exp - tp)
        # Aggregate fractional coverage credits (required); compute coverage_recall when exp>0
        coverage_recall_val: float | None = None
        if exp > 0:
            # Validate IDs and aggregate credits per canonical TP
            per_canon: dict[str, float] = {}
            for credit in result.coverage_credits:
                cid = credit.canon_id
                rid = credit.crit_id
                # Validate canonical ID (must be TP set)
                if cid not in allowed_tp_ids:
                    raise ValueError(f"coverage_credits contains non-canonical TP id: {cid}")
                # Validate critique ID if known
                if allowed_critique_ids and rid not in allowed_critique_ids:
                    raise ValueError(f"coverage_credits contains non-critique id: {rid}")
                # Accumulate credit; clamp later when computing recall
                per_canon[cid] = per_canon.get(cid, 0.0) + float(credit.credit)
            # Compute recall as average of clamped per-canonical totals
            total = 0.0
            for v in per_canon.values():
                total += min(1.0, max(0.0, v))
            coverage_recall_val = max(0.0, min(1.0, total / exp))

        metrics = GradeMetrics(
            expected=exp,
            reported=rep,
            true_positives=tp,
            false_positive=fp,
            unknown=unk,
            false_negatives=fn,
            precision=float(result.precision),
            recall=float(result.recall),
            coverage_recall=coverage_recall_val,
        )
        state.result = GradeSubmitPayload(
            metrics=metrics,
            true_positive_ids=list(result.true_positive_ids),
            false_positive_ids=list(result.false_positive_ids),
            unknown_critique_ids=list(result.unknown_critique_ids),
            message_md=result.message_md,
        )
        return SimpleOk(ok=True)


def make_grader_submit_server(
    state: GradeSubmitState, *, name: str = "grader_submit", inputs: GradeInputs
) -> NotifyingFastMCP:
    """Exposes submit_result(result: GradeSubmitInput) -> {ok: True}.

    Validates returned IDs and computes metrics server-side using specimen + critique context.
    """

    mcp = NotifyingFastMCP(name, instructions="Final grader submission for specimen critique evaluation")
    build_grader_submit_tools(mcp, state, inputs=inputs)

    return mcp


class CoverageCredit(BaseModel):
    """Fractional credit from a critique item to a canonical positive.

    - crit_id: critique item ID (must be in the critique set; prefixed with crit_)
    - canon_id: canonical positive ID (must be in the canonical TP set; prefixed with canon_tp_)
    - credit: fraction in [0.0, 1.0]; server aggregates across critique items and clamps per-canonical totals to 1.0
    """

    crit_id: str = Field(..., description="Critique item ID (crit_ prefix)")
    canon_id: str = Field(..., description="Canonical positive ID (canon_tp_ prefix)")
    credit: float = Field(
        ..., ge=0.0, le=1.0, description="Fractional credit [0,1] from this critique item toward the canonical"
    )


def make_grader_submit_server_from_inputs(
    state: GradeSubmitState, *, name: str = "grader_submit", inputs: GradeInputs
) -> NotifyingFastMCP:
    """Thin wrapper: pass GradeInputs through to the primary builder.

    The main make_grader_submit_server() derives allowed IDs and counts internally.
    """
    return make_grader_submit_server(state, name=name, inputs=inputs)


@render_to_rich.register
def _render_grade_submit_payload(obj: GradeSubmitPayload):
    """Rich renderer for GradeSubmitPayload (concise summary)."""
    bits: list[RenderableType] = []

    if obj.metrics is not None:
        m = obj.metrics
        tbl = Table(title="Grading Summary", show_lines=False, expand=True)
        tbl.add_column("Metric", style="cyan")
        tbl.add_column("Value", style="magenta")
        rows: list[tuple[str, str]] = [
            ("expected", str(m.expected)),
            ("reported", str(m.reported)),
            ("true_positives", str(m.true_positives)),
            ("false_positive", str(m.false_positive)),
            ("unknown", str(m.unknown)),
            ("false_negatives", str(m.false_negatives)),
            ("precision", f"{m.precision:.3f}"),
            ("recall", f"{m.recall:.3f}"),
        ]
        if m.coverage_recall is not None:
            rows.append(("coverage_recall", f"{m.coverage_recall:.3f}"))
        for k, v in rows:
            tbl.add_row(k, v)
        bits.append(tbl)

    # Optionally show categorized IDs (truncated)
    id_tbl = Table(title="IDs (truncated)", show_lines=False, expand=True)
    id_tbl.add_column("Category", style="cyan")
    id_tbl.add_column("IDs", style="magenta")

    def _short(xs: list[str]) -> str:
        return ", ".join(xs[:10]) + (" …" if len(xs) > 10 else "")

    if obj.true_positive_ids:
        id_tbl.add_row("true_positive_ids", _short(obj.true_positive_ids))
    if obj.false_positive_ids:
        id_tbl.add_row("false_positive_ids", _short(obj.false_positive_ids))
    if obj.unknown_critique_ids:
        id_tbl.add_row("unknown_critique_ids", _short(obj.unknown_critique_ids))
    if len(id_tbl.rows) > 0:
        bits.append(id_tbl)

    if obj.message_md:
        bits.append(Markdown(obj.message_md))

    body: RenderableType = bits[0] if len(bits) == 1 else Group(*bits)
    title = "Grader result"
    return Panel(body, title=title, border_style="blue")
