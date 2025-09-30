"""Critic MCP server and CriticSubmitPayload models.

This module defines the strict structured output used by the critic agent (codebase → candidate issues)
and a tiny FastMCP server that accepts exactly one submission per run via submit_result.

Candidate issues are expressed as IssueCore + Occurrence(s); freeform notes allowed only via notes_md.
Payload is validated with Pydantic.

Critic agent MUST call submit_result(result) where result conforms to CriticSubmitPayload.
"""

from __future__ import annotations

from typing import Any, Annotated

from adgn.mcp._shared.fastmcp_helpers import SafeFastMCP
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from adgn.props.models.issue import IssueId, Occurrence, LineRange
from adgn.llm.rendering.rich_renderers import render_to_rich


class ReportedIssue(BaseModel):
    """Candidate issue reported by the critic (flattened header).

    Exposes only id and rationale; internal-only fields like should_flag/gap_note are not part of the critic schema.

    Note: occurrences may be empty while the critique is being built incrementally; the submit tool enforces ≥1.
    """

    id: IssueId
    rationale: str
    occurrences: list[Occurrence] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class CriticSubmitPayload(BaseModel):
    """Structured critic output."""

    issues: list[ReportedIssue] = Field(
        default_factory=list,
        description="Issues found",
    )
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
    # In-progress incremental payload (used by upsert/add_* tools before submit)
    work: CriticSubmitPayload | None = None


# --- Incremental tool input models (module-scope to avoid ForwardRef issues) ---
RangeAtom = int | list[int]


class UpsertIssueInput(BaseModel):
    """Create or update an issue header (id + rationale)."""

    issue_id: IssueId
    description: str = Field(description="Issue rationale/description")

    model_config = ConfigDict(extra="forbid")


class CancelIssueInput(BaseModel):
    """Remove an issue and all its occurrences by id."""

    issue_id: IssueId

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceInput(BaseModel):
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """

    issue_id: IssueId
    file: Annotated[str, StringConstraints(pattern=r"^[^\n]+$")]
    ranges: Annotated[
        list[RangeAtom],
        Field(
            min_items=1, description="List of single lines (int) or spans [start,end]"
        ),
    ]

    model_config = ConfigDict(extra="forbid")


class SubmitInput(BaseModel):
    """Finalize: the model must state the number of issues it believes it created."""

    issues: int = Field(
        ge=0, description="Count of issues in the critique at submit time"
    )

    model_config = ConfigDict(extra="forbid")


class AddOccurrenceFilesInput(BaseModel):
    """Add one occurrence spanning multiple files and ranges.

    files: map of file -> list of range atoms (int or [start,end]).
    """

    issue_id: IssueId
    files: dict[Annotated[str, StringConstraints(pattern=r"^[^\n]+$")], list[RangeAtom]]

    model_config = ConfigDict(extra="forbid")


CRITIC_MCP_INSTRUCTIONS = (
    "Critique builder: upsert issues, add occurrences, and submit when complete.\n"
    "Tools:\n"
    "- upsert_issue(issue_id, description): Create or update an issue header (id, rationale).\n"
    "- cancel_issue(issue_id): Remove an issue and all its occurrences.\n"
    "- add_occurrence(issue_id, file, ranges): Add one occurrence for an issue. ranges accepts items like 123 or [140,150].\n"
    '- add_occurrence_files(issue_id, files): Add a single occurrence spanning multiple files and ranges (files is a map: {"a.py":[123,[140,150]], "b.py":[[5,7]]}).\n'
    "- show_critique(): Return the current structured critique.\n"
    "- submit(issues): Validate the count matches current critique; returns Ok/Err.\n"
    "- report_failure(error): Report that critique could not be completed (e.g., no files matched scope, access errors).\n\n"
    "Notes:\n"
    "- Multi-occurrence issues: call add_occurrence multiple times for the same issue.\n"
    "- Cross-file support: use add_occurrence_files to express one occurrence that spans multiple files/ranges.\n\n"
    "Example:\n"
    "\n"
    "# One file, three occurrences:\n"
    "upsert_issue(\"iss-001\", \"Avoid broad exception handling: replace bare 'except' or 'except Exception' with specific exceptions; do not swallow errors. Surface unexpected failures and keep handlers minimal.\")\n"
    'add_occurrence("iss-001", "pkg/a.py", [123])\n'
    'add_occurrence("iss-001", "pkg/a.py", [[140,150]])\n'
    'add_occurrence("iss-001", "pkg/a.py", [200, 205, [210, 220]])\n'
    "\n"
    "# One occurrence over multiple files/ranges:\n"
    'upsert_issue("iss-002", "Pydantic v2 migration: stop mixing legacy Config class with v2 validators; use model_config=ConfigDict(...) and model_validator consistently across models.")\n'
    'add_occurrence_files("iss-002", {"pkg/a.py":[[10,12],20], "pkg/b.py":[[5,7]]})\n'
    "\n"
    "submit(issues=2)  # review complete, iss-001, iss-002\n"
)


def make_critic_submit_server(
    state: CriticSubmitState,
    *,
    name: str = "critic_submit",
) -> SafeFastMCP:
    """Create a FastMCP exposing submit_result(result: CriticSubmitPayload) -> {ok: True}.

    Agent must call submit_result exactly once to deliver a validated CriticSubmitPayload.
    Payload is validated with Pydantic and stored in state.result. Invalid payloads
    will raise and be returned to the caller as an error.
    """

    mcp = SafeFastMCP(
        name,
        instructions=CRITIC_MCP_INSTRUCTIONS,
    )

    # --- New incremental tooling (simpler structure) ---

    def _ensure_work_payload() -> CriticSubmitPayload:
        work = state.work
        if work is None:
            work = CriticSubmitPayload()
            state.work = work
        return work

    def _normalize_ranges(atoms: list[RangeAtom]) -> list[LineRange]:
        out: list[LineRange] = []
        for a in atoms:
            if isinstance(a, int):
                out.append(LineRange(start_line=int(a)))
            elif (
                isinstance(a, list)
                and len(a) == 2
                and all(isinstance(x, int) for x in a)
            ):
                start, end = int(a[0]), int(a[1])
                out.append(LineRange(start_line=start, end_line=end))
            else:
                raise ValueError(
                    "ranges items must be int or [start,end]",
                )
        return out

    @mcp.tool()
    async def upsert_issue(payload: UpsertIssueInput) -> dict[str, Any]:
        """Upsert issue(issue_id, description). Returns guidance on next steps."""
        work = _ensure_work_payload()
        # Replace or insert
        for idx, it in enumerate(work.issues):
            if it.id == payload.issue_id:
                work.issues[idx] = ReportedIssue(
                    id=payload.issue_id,
                    rationale=payload.description,
                    occurrences=it.occurrences,
                )
                break
        else:
            work.issues.append(
                ReportedIssue(
                    id=payload.issue_id, rationale=payload.description, occurrences=[]
                )
            )
        return {
            "ok": True,
            "message": f"issue {payload.issue_id} noted. note: you need to use add_occurrence to mark the site of at least one occurrence",
        }

    @mcp.tool()
    async def cancel_issue(payload: CancelIssueInput) -> dict[str, Any]:
        """Cancel issue(issue_id) and remove all its occurrences."""
        work = _ensure_work_payload()
        work.issues = [it for it in work.issues if it.id != payload.issue_id]
        after_issues = len(work.issues)
        after_occs = sum(len(i.occurrences) for i in work.issues)
        return {
            "ok": True,
            "message": f"issue {payload.issue_id} canceled. {after_issues} issues ({after_occs} occurrences) noted.",
        }

    @mcp.tool()
    async def add_occurrence(payload: AddOccurrenceInput) -> dict[str, Any]:
        """Add occurrence(issue_id, file, ranges). ranges: [123, [140,150]]."""
        work = _ensure_work_payload()
        # Find issue
        for it in work.issues:
            if it.id == payload.issue_id:
                occ = Occurrence(
                    files={payload.file: _normalize_ranges(payload.ranges)}
                )
                it.occurrences.append(occ)
                total_occs = sum(len(i.occurrences) for i in work.issues)
                return {
                    "ok": True,
                    "message": f"occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted.",
                    "occurrences": total_occs,
                }
        return {
            "ok": False,
            "code": "UNKNOWN_ISSUE",
            "error": f"unknown issue_id: {payload.issue_id}",
            "details": {"issue_id": str(payload.issue_id)},
        }

    @mcp.tool()
    async def show_critique() -> CriticSubmitPayload:
        """Return the current critique (issues + occurrences)."""
        return _ensure_work_payload()

    @mcp.tool()
    async def add_occurrence_files(payload: AddOccurrenceFilesInput) -> dict[str, Any]:
        """Add a single occurrence with multiple files/ranges via files map."""
        work = _ensure_work_payload()
        for it in work.issues:
            if it.id == payload.issue_id:
                files_map = {
                    path: _normalize_ranges(ranges)
                    for path, ranges in (payload.files or {}).items()
                }
                occ = Occurrence(files=files_map)
                it.occurrences.append(occ)
                total_occs = sum(len(i.occurrences) for i in work.issues)
                return {
                    "ok": True,
                    "message": f"multi-file occurrence recorded for {payload.issue_id}. {total_occs} total occurrences noted.",
                    "occurrences": total_occs,
                }
        return {
            "ok": False,
            "code": "UNKNOWN_ISSUE",
            "error": f"unknown issue_id: {payload.issue_id}",
            "details": {"issue_id": str(payload.issue_id)},
        }

    @mcp.tool()
    async def submit(payload: SubmitInput) -> dict[str, Any]:
        """Finalize: validate each issue has ≥1 occurrence, check count, and persist as result.

        Returns a structured status dict instead of raising for normal usage errors:
        - {ok: False, code: "ALREADY_SUBMITTED"}
        - {ok: False, code: "MISSING_OCCURRENCES", details: {issue_ids: [...]}}
        - {ok: False, code: "COUNT_MISMATCH", details: {reported: n, actual: m}}
        - On success: {ok: True, issues: n, occurrences: m}
        """
        if (state.result is not None) or (state.error is not None):
            return {
                "ok": False,
                "code": "ALREADY_SUBMITTED",
                "error": "submit already called (result or error set)",
            }
        work = _ensure_work_payload()
        missing = [it.id for it in work.issues if not it.occurrences]
        if missing:
            return {
                "ok": False,
                "code": "MISSING_OCCURRENCES",
                "error": "cannot submit: issues without occurrences",
                "details": {"issue_ids": [str(x) for x in missing]},
            }
        actual_issues = len(work.issues)
        if payload.issues != actual_issues:
            return {
                "ok": False,
                "code": "COUNT_MISMATCH",
                "error": "submit count mismatch",
                "details": {"reported": payload.issues, "actual": actual_issues},
            }
        state.result = work
        occs = sum(len(i.occurrences) for i in work.issues)
        return {"ok": True, "issues": actual_issues, "occurrences": occs}

    @mcp.tool()
    async def report_failure(error: CriticErrorPayload) -> dict[str, Any]:
        """Report a failure to complete the critique (operational or scope issues)."""
        if (state.result is not None) or (state.error is not None):
            return {
                "ok": False,
                "code": "ALREADY_SUBMITTED",
                "error": "submit already called (result or error set)",
            }
        state.error = error
        return {"ok": False}

    # --- Legacy tools kept for compatibility ---
    # @mcp.tool()  # disabled legacy batch submit
    async def submit_result(result: CriticSubmitPayload) -> dict[str, Any]:
        """[Legacy DISABLED] Submit the entire structured result in one call."""
        if (state.result is not None) or (state.error is not None):
            raise ValueError("submit already called (result or error set)")
        state.result = result
        return {"ok": True}

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
            cid = ci.id or "(no id)"
            rationale = ci.rationale or ""
            occs = []
            for occ in ci.occurrences:
                files = []
                for p, ranges in (occ.files or {}).items():
                    if ranges is None:
                        files.append(f"{p}: (unspecified)")
                    else:
                        spans = ", ".join(
                            f"{r.start_line}"
                            + (f"-{r.end_line}" if r.end_line is not None else "")
                            for r in ranges
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
