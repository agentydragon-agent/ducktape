from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

# ---------- Families and grouping -------------------------------------------


class Family(StrEnum):
    GPT_5 = "gpt-5"
    O3 = "o3"
    O4_MINI = "o4-mini"
    O1 = "o1"
    GPT_41 = "gpt-4.1"
    OTHER = "other"


FAMILY_RULES: dict[Family, str] = {
    Family.GPT_5: r"^gpt[-_]?5(?!-(mini|nano))",
    Family.O3: r"^o3(?!-mini)",
    Family.O4_MINI: r"^o4-mini",
    Family.O1: r"^o1(?!-mini)",
    Family.GPT_41: r"^gpt[-_]?4\.1(?!-(mini|nano))",
}
FAMILY_RES = {fam: re.compile(pattern, re.IGNORECASE) for fam, pattern in FAMILY_RULES.items()}

# Global family priority for ordering
FAMILY_PRIORITY: list[Family] = [Family.GPT_5, Family.O3, Family.O4_MINI, Family.O1, Family.GPT_41]


def family_of(mid: str) -> Family:
    for fam, rx in FAMILY_RES.items():
        if rx.search(mid):
            return fam
    return Family.OTHER


# ---------- Error classification surface (shared enums only) -----------------


class ErrorCode(StrEnum):
    MISSING_TOOLS_NAME = "MISSING-TOOLS-NAME"
    RATE_LIMIT = "RATE-LIMIT"
    TOO_LARGE = "TOO-LARGE"
    NO_CAP = "NO-CAP"
    RESP_ONLY = "RESP-ONLY"
    NOT_CHAT = "NOT-CHAT"
    TIMEOUT = "TIMEOUT"
    INVALID_OUTPUT = "INVALID-OUTPUT"
    SERVER_ERROR = "SERVER-ERROR"
    NOT_FOUND = "NOT-FOUND"
    TOOLS_UNSUPPORTED = "TOOLS-UNSUPPORTED"
    FORBIDDEN = "FORBIDDEN"
    AUDIO_REQUIRED = "AUDIO-REQUIRED"
    INVALID_HEADERS = "INVALID-HEADERS"
    INVALID_REQUEST = "INVALID-REQUEST"
    TTS_MODEL = "TTS-MODEL"
    OTHER = "OTHER"


# Fatal (non-repeatable) error codes — cancel remaining repeats on first occurrence
FATAL_CODES: set[ErrorCode] = {
    ErrorCode.TTS_MODEL,
    ErrorCode.INVALID_REQUEST,
    ErrorCode.INVALID_HEADERS,
    ErrorCode.AUDIO_REQUIRED,
    ErrorCode.FORBIDDEN,
    ErrorCode.TOOLS_UNSUPPORTED,
    ErrorCode.NOT_FOUND,
    ErrorCode.NOT_CHAT,
    ErrorCode.RESP_ONLY,
}


# ---------- Data containers used by UI --------------------------------------


@dataclass(frozen=True)
class ProbeRun:
    model_id: str
    calls: list[Any]

    @property
    def ok(self) -> bool:
        return any(c.ok for c in self.calls)

    @property
    def avg_latency_s(self) -> float | None:
        vals = [c.latency_s for c in self.calls if c.ok and c.latency_s is not None]
        nums = [float(v) for v in vals if isinstance(v, int | float)]
        return (sum(nums) / len(nums)) if nums else None


@dataclass(frozen=True)
class ModelProbe:
    model_id: str
    responses: ProbeRun
    chat: ProbeRun

    @property
    def any_ok(self) -> bool:
        return self.responses.ok or self.chat.ok


# ---------- Cell stats and formatting ---------------------------------------


@dataclass(frozen=True)
class CellStats:
    total: int
    ok: int
    success_rate_pct: int
    succ_avg_s: float | None
    succ_std_s: float | None
    first_snippet: str | None
    top_error_code: ErrorCode | None
    top_error_desc: str | None
    error_kinds: int


def compute_cell_stats(calls: list[Any]) -> CellStats:
    total = len(calls)
    ok_calls = [c for c in calls if c.ok]
    ok = len(ok_calls)
    success_rate_pct = round((ok / total) * 100) if total else 0

    # Latency among successful
    succ_lats = [float(c.latency_s) for c in ok_calls if c.latency_s is not None]
    succ_avg_s = (sum(succ_lats) / len(succ_lats)) if succ_lats else None
    succ_std_s: float | None = None
    if succ_lats and len(succ_lats) >= 2 and succ_avg_s is not None:
        m = succ_avg_s
        var_val = sum((x - m) ** 2 for x in succ_lats) / len(succ_lats)
        succ_std_s = var_val**0.5

    # First success snippet if any
    first_snippet: str | None = None
    for c in ok_calls:
        if isinstance(c.content, str) and c.content:
            first_snippet = c.content
            break

    # Error summary among unsuccessful
    err_codes: list[ErrorCode] = []
    code_desc: dict[ErrorCode, str] = {}
    for c in calls:
        if not c.ok:
            classification = c.error_classification
            if classification:
                code, desc = classification
                if isinstance(code, ErrorCode):
                    err_codes.append(code)
                    code_desc.setdefault(code, desc)
    top_error_code: ErrorCode | None = None
    top_error_desc: str | None = None
    error_kinds = 0
    if err_codes:
        cnt = Counter(err_codes)
        top_error_code = cnt.most_common(1)[0][0]
        top_error_desc = code_desc.get(top_error_code)
        error_kinds = len(cnt)

    return CellStats(
        total=total,
        ok=ok,
        success_rate_pct=success_rate_pct,
        succ_avg_s=succ_avg_s,
        succ_std_s=succ_std_s,
        first_snippet=first_snippet,
        top_error_code=top_error_code,
        top_error_desc=top_error_desc,
        error_kinds=error_kinds,
    )


def build_cell(calls: list[Any]) -> tuple[str, ErrorCode | None, str | None]:
    """Build a single rich cell with success rate, success latency, and top error."""
    if not calls:
        return ("[yellow]waiting…[/yellow]", None, None)

    stats = compute_cell_stats(calls)

    parts: list[str] = [f"{stats.success_rate_pct}%"]
    if stats.succ_avg_s is not None:
        parts.append(f"{stats.succ_avg_s:.1f}s")
    code_ret: ErrorCode | None = None
    desc_ret: str | None = None
    if stats.ok < stats.total and stats.top_error_code is not None:
        plus = "+" if stats.error_kinds > 1 else ""
        parts.append(f"e={stats.top_error_code.value}{plus}")
        code_ret = stats.top_error_code
        desc_ret = stats.top_error_desc
    suffix = f" [{'|'.join(parts)}]" if parts else ""

    if stats.ok > 0:
        base = (stats.first_snippet or "").removeprefix("✓ ").strip()
        if base == "tool OK":
            base = ""
        if base:
            return (f"[green]✓ {base}{suffix}[/green]", code_ret, desc_ret)
        return (f"[green]✓{suffix}[/green]", code_ret, desc_ret)

    code_txt = stats.top_error_code.value if stats.top_error_code else "ERROR"
    plus = "+" if stats.error_kinds > 1 else ""
    return (f"[red]{code_txt}{plus} [{stats.success_rate_pct}%][/red]", stats.top_error_code, stats.top_error_desc)
