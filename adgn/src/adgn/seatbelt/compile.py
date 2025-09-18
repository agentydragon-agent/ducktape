"""
SBPL compiler: SBPLPolicy -> SBPL text.

Pure function: no mutations, no auto-inserted paths or platform probing.
"""

from __future__ import annotations

from collections.abc import Iterable

from .model import FileRule, NetworkRule, PathFilter, SBPLPolicy


def _q(s: str) -> str:
    # Minimal quote for SBPL string literals
    # TODO(mpokorny): Verify SBPL quoting coverage (backslashes, quotes, non-ASCII/UTF-8, control chars). Add round-trip tests; extend escaping (e.g., parentheses?) if needed.
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _render_path_filter(pf: PathFilter) -> str:
    if pf.kind == "literal":
        return f'(literal "{_q(pf.value)}")'
    if pf.kind == "subpath":
        return f'(subpath "{_q(pf.value)}")'
    # Should be unreachable due to typing
    raise ValueError(f"unsupported PathFilter kind: {pf.kind}")


def _render_file_rule(fr: FileRule) -> Iterable[str]:
    # file-map-executable typically has no filters; if none, emit a bare allow/deny line.
    if not fr.filters:
        yield f"({fr.action} {fr.op})"
        return
    for pf in fr.filters:
        yield f"({fr.action} {fr.op} {_render_path_filter(pf)})"


def _render_network_rule(nr: NetworkRule) -> str:
    pred = " (local ip)" if nr.local_only else ""
    return f"({nr.action} {nr.op}{pred})"


def compile_sbpl(policy: SBPLPolicy) -> str:
    """Compile SBPLPolicy to SBPL text.

    No validation beyond shape typing; callers may run validators separately.
    """
    lines: list[str] = []

    # Header
    lines.append("(version 1)")
    lines.append(f"({policy.default_behavior} default)")

    # Trace
    if policy.trace.enabled and policy.trace.path:
        lines.append(f'(trace "{_q(policy.trace.path)}")')
        # Magic: ensure trace path is writable by the sandbox so the trace file can be created
        # TODO(mpokorny): This is implicit rule injection; consider making it explicit or configurable.
        lines.append(f'(allow file-write* (literal "{_q(policy.trace.path)}"))')

    # Process primitives
    if policy.process.allow_process_star:
        lines.append("(allow process*)")
    else:
        lines.append("(deny process*)")
    if policy.process.allow_signal_self:
        lines.append("(allow signal (target self))")
    else:
        lines.append("(deny signal (target self))")

    # File rules (in given order)
    for fr in policy.files:
        lines.extend(_render_file_rule(fr))

    # Network rules
    for nr in policy.network:
        lines.append(_render_network_rule(nr))

    # System toggles
    if policy.system.system_socket:
        lines.append("(allow system-socket)")
    if policy.system.sysctl_read:
        lines.append("(allow sysctl-read)")

    # Mach lookup
    for name in policy.mach.global_names:
        lines.append(f'(allow mach-lookup (global-name "{_q(name)}"))')

    lines.append("")
    return "\n".join(lines)
