"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via submit_result.

Key constraints enforced here:
- No provenance, no suggested patches, no top-level pass/fail booleans.
- Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
- The MCP server validates the payload using Pydantic and stores the parsed manifest in the provided state.

The critic agent MUST call submit_result(result) where result conforms to CriticSubmitPayload.
"""

from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field, model_validator
from mcp.server.fastmcp import FastMCP

from adgn_llm.properties.models.issue import IssueCore, Occurrence

from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.console import Group, RenderableType
from adgn_llm.rendering.rich_renderers import render_to_rich


class ReportedIssue(BaseModel):
    """Candidate issue: IssueCore metadata + >=1 Occurrence(s)."""

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

    issues: List[ReportedIssue] = Field(default_factory=list, description="List of issues found")
    notes_md: str | None = Field(
        default=None,
        description="Optional Markdown note. Only for info not represented in structured form in `issues`.",
    )
    model_config = ConfigDict(extra="forbid")


class CriticSubmitState:
    """Container for the single submitted CriticSubmitPayload result."""

    result: CriticSubmitPayload | None = None


def make_critic_submit_server(state: CriticSubmitState, *, name: str = "critic_submit") -> FastMCP:
    """Create a FastMCP exposing submit_result(result: CriticSubmitPayload) -> {ok: True}.

    Agent must call submit_result exactly once to deliver a validated CriticSubmitPayload.
    Server validates payload with Pydantic and stores it in state.result. Invalid payloads
    will raise and be returned to the caller as an error.
    """

    mcp = FastMCP(name, instructions="Final critic submission for specimen scan")

    @mcp.tool()
    async def submit_result(result: CriticSubmitPayload) -> dict[str, Any]:
        # Payload is already validated by FastMCP via type annotation
        state.result = result
        return {"ok": True}

    return mcp


@render_to_rich.register
def _render_critic_submit_payload(obj: CriticSubmitPayload):  # type: ignore[misc]
    bits: list[RenderableType] = []
    # Candidate issues table
    tbl = Table(title="Candidate Issues", show_lines=False, expand=True)
    tbl.add_column("ID", style="cyan")
    tbl.add_column("Properties", style="magenta")
    tbl.add_column("Rationale", style="green")
    tbl.add_column("Occurrences", style="yellow")

    if obj.issues:
        for ci in obj.issues:
            cid = ci.core.id or "(no id)"
            props = ", ".join(ci.core.properties or [])
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
            tbl.add_row(cid, props, rationale, occs_text)
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
