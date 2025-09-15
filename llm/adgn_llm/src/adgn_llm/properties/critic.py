"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via submit_result.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call submit_result(result) where result conforms to CriticSubmitPayload.
"""

from __future__ import annotations
from typing import Any, List
from pydantic import BaseModel, ConfigDict, Field, model_validator
from mcp.server.fastmcp import FastMCP
from adgn_llm.properties.models.issue import IssueCore, Occurrence
from adgn_llm.rendering.rich_renderers import render_to_rich
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Group, RenderableType


class ReportedIssue(BaseModel):
    """Candidate issue: IssueCore header + >=1 Occurrence(s)."""

    core: IssueCore
    occurrences: list[Occurrence]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _validate_occurrences_present(self) -> "ReportedIssue":
        if not self.occurrences:
            raise ValueError("ReportedIssue must include at least one Occurrence")
        return self


class CriticSubmitPayload(BaseModel):
    """Structured critic output."""

    issues: List[ReportedIssue] = Field(default_factory=list, description="Issues found")
    notes_md: str | None = Field(
        default=None,
        description="Optional Markdown note. Only for info not represented in structured form in `issues`.",
    )
    model_config = ConfigDict(extra="forbid")


class CriticErrorPayload(BaseModel):
    """Structured error report from critic when it cannot produce findings."""

    message: str = Field(description="Human-readable error summary")
    model_config = ConfigDict(extra="forbid")


class CriticSubmitState:
    """Container for submitted CriticSubmitPayload or an error."""

    result: CriticSubmitPayload | None = None
    error: CriticErrorPayload | None = None


def make_critic_submit_server(state: CriticSubmitState, *, name: str = "critic_submit") -> FastMCP:
    """Create a FastMCP exposing submit_result(result: CriticSubmitPayload) -> {ok: True}.

    Agent must call submit_result exactly once to deliver a validated CriticSubmitPayload.
    Payload is validated with Pydantic and stored in state.result. Invalid payloads
    will raise and be returned to the caller as an error.
    """

    mcp = FastMCP(
        name,
        instructions=(
            "Used to submit final complete critique or report a blocking error. "
            "Tools: submit_result(result) for success; submit_error(error) for unrecoverable errors. "
            "NOTE: either tool will complete your turn; call exactly once."
        ),
    )

    @mcp.tool()
    async def submit_result(result: CriticSubmitPayload) -> dict[str, Any]:
        # Payload is already validated by FastMCP via type annotation
        if getattr(state, "result", None) is not None or getattr(state, "error", None) is not None:
            raise ValueError("submit already called (result or error set)")
        state.result = result
        return {"ok": True}

    @mcp.tool()
    async def submit_error(error: CriticErrorPayload) -> dict[str, Any]:
        if getattr(state, "result", None) is not None or getattr(state, "error", None) is not None:
            raise ValueError("submit already called (result or error set)")
        state.error = error
        return {"ok": False}

    return mcp


@render_to_rich.register
def _render_critic_submit_payload(obj: CriticSubmitPayload):  # type: ignore[misc]
    bits: list[RenderableType] = []
    # Candidate issues table (no properties column)
    tbl = Table(title="Candidate Issues", show_lines=False, expand=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Rationale", style="green")
    tbl.add_column("Occurrences", style="yellow")

    if obj.issues:
        for ci in obj.issues:
            cid = ci.core.id or "(no id)"
            rationale = ci.core.rationale or ""
            occs = []
            for occ in ci.occurrences:
                files = []
                for p, ranges in (occ.files or {}).items():
                    if ranges is None:
                        files.append(f"{p}: (unspecified)")
                    else:
                        spans = ", ".join(
                            f"{r.start_line}" + (f"-{r.end_line}" if r.end_line is not None else "") for r in ranges
                        )
                        files.append(f"{p}: {spans}")
                note = f" ({occ.note})" if occ.note else ""
                occs.append("; ".join(files) + note)
            occs_text = "\n".join(occs)
            tbl.add_row(cid, rationale, occs_text)
    else:
        tbl.add_row("(no candidate issues)", "", "", "")

    bits.append(tbl)
    if obj.notes_md:
        bits.append(Markdown(obj.notes_md))

    if len(bits) == 1:
        body: RenderableType = bits[0]
    else:
        # simple group rendering for multiple blocks
        body = Group(*bits)

    title = f"Critic result ({len(obj.issues)} issues)"
    border = "red" if obj.issues else "green"
    return Panel(body, title=title, border_style=border)


@render_to_rich.register
def _render_critic_error_payload(obj: CriticErrorPayload):  # type: ignore[misc]
    body: RenderableType = Markdown(obj.message)
    return Panel(body, title="Critic error", border_style="red")
