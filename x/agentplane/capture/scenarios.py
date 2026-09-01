"""The explicit provider-by-scenario discovery matrix.

Scenario implementations intentionally remain provider-specific.  This registry makes a
missing implementation impossible to mislabel as native ``unsupported``.
"""

from __future__ import annotations

SCENARIOS = (
    "launch_handshake",
    "baseline",
    "shell",
    "file_edits",
    "structured_tools",
    "steering",
    "normal_submit_while_active",
    "dequeue_pending_input",
    "interrupt_with_queued_input",
    "interrupt",
    "kill_idle_resume",
    "kill_active_reconcile_resume",
    "pod_replacement",
)
PROVIDERS = ("claude", "codex")


def require_scenario(provider: str, scenario: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
