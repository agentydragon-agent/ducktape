"""Grader MCP server and GradeSubmitPayload models.

Defines structured output used by critique grader:
(specimen canonical issues + input critique JSON → metrics + markdown summary)
AND a tiny FastMCP server that accepts exactly one submission per run via
submit_result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from mcp.server.fastmcp import FastMCP

from adgn_llm.rendering.rich_renderers import render_to_rich
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Group, RenderableType


class GradeMetrics(BaseModel):
    """Basic grading metrics (no per-property breakdown)."""

    expected: int = Field(..., description="Number of canonical items (ground truth)")
    reported: int = Field(..., description="Number of items reported by critique")
    true_positives: int = Field(..., description="Reported items that match canonical")
    false_positive: int = Field(
        ..., description="Reported items known to be false positives (in known-FP list)"
    )
    unknown: int = Field(
        ...,
        description="Reported items neither in canonical positives nor in known false positives",
    )
    false_negatives: int = Field(..., description="Canonical items missing in report")
    precision: float = Field(
        ..., description="TP / (TP + false_positive + unknown); 0.0 if undefined"
    )
    recall: float = Field(
        ..., description="TP / expected (known-positives); 0.0 if undefined"
    )

    model_config = ConfigDict(extra="forbid")


class GradeSubmitPayload(BaseModel):
    """Structured grader output: metrics + optional writeup."""

    metrics: GradeMetrics
    message_md: str | None = Field(
        default=None,
        description="Optional Markdown summary/notes; may include tables of examples",
    )

    model_config = ConfigDict(extra="forbid")


class GradeSubmitState:
    """Container for submitted GradeSubmitPayload."""

    result: GradeSubmitPayload | None = None


def make_grader_submit_server(
    state: GradeSubmitState, *, name: str = "grader_submit"
) -> FastMCP:
    """Exposes submit_result(result: GradeSubmitPayload) -> {ok: True}.

    Agent must call submit_result to deliver a validated GradeSubmitPayload.
    """
    mcp = FastMCP(
        name, instructions="Final grader submission for specimen critique evaluation"
    )

    @mcp.tool()
    async def submit_result(result: GradeSubmitPayload) -> dict[str, Any]:  # noqa: D401
        """Submit the final grading result."""
        state.result = result
        return {"ok": True}

    return mcp


@render_to_rich.register
def _render_grade_submit_payload(obj: GradeSubmitPayload):  # type: ignore[misc]
    """Rich renderer for GradeSubmitPayload (concise summary)."""
    bits: list[RenderableType] = []

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
    for k, v in rows:
        tbl.add_row(k, v)

    bits.append(tbl)
    if obj.message_md:
        bits.append(Markdown(obj.message_md))

    body: RenderableType = bits[0] if len(bits) == 1 else Group(*bits)
    title = "Grader result"
    return Panel(body, title=title, border_style="blue")
