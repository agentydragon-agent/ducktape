"""Opt-in live native-wire capture runner.

This runner refuses implicit model/budget/credential choices.  Offline replay does not
invoke it and never needs a harness binary, network, or credential.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from x.agentplane.capture.artifacts import CaptureBundle
from x.agentplane.capture.binary_resolution import resolve_binary
from x.agentplane.capture.credential_boundary import credential_environment, read_runtime_key, sanitize_environment
from x.agentplane.capture.providers.claude import driver as claude
from x.agentplane.capture.providers.codex import driver as codex
from x.agentplane.capture.scenarios import SCENARIOS, require_scenario
from x.agentplane.capture.workspace import diff, snapshot


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("claude", "codex"), required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--model", required=True, help="Explicit cheap-experiments allowlisted model")
    parser.add_argument("--effort", required=True, help="Lowest accepted provider reasoning/effort")
    parser.add_argument("--max-calls", type=int, required=True)
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--max-spend-usd", type=float, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True, help="LiteLLM origin, recorded without credential")
    parser.add_argument(
        "--credential-file", type=Path, required=True, help="0600 file containing temporary virtual key"
    )
    parser.add_argument("--claude-bin")
    parser.add_argument("--codex-bin")
    parser.add_argument("--acknowledge-destructive", action="store_true")
    return parser


def _validate(args: argparse.Namespace) -> None:
    if args.max_calls < 0 or args.max_tokens <= 0 or args.max_spend_usd <= 0:
        raise ValueError("finite positive token/spend ceilings and nonnegative call ceiling are required")
    if args.scenario == "pod_replacement" and not args.acknowledge_destructive:
        raise ValueError("pod_replacement requires --acknowledge-destructive")
    if not args.workspace.is_dir():
        raise ValueError("workspace must already be a fresh synthetic directory")
    if args.artifact_dir.exists():
        raise ValueError("artifact directory must not exist")


def _initial_frames(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.provider == "claude":
        return [claude.initialize()]
    return [
        codex.initialize("capture-1"),
        codex.initialized(),
        codex.thread_start("capture-2", cwd=str(args.workspace), model=args.model, effort=args.effort),
    ]


def run(args: argparse.Namespace) -> Path:
    _validate(args)
    require_scenario(args.provider, args.scenario)
    binary = resolve_binary(args.provider, getattr(args, f"{args.provider}_bin"))
    key = read_runtime_key(args.credential_file)
    environment = credential_environment(key=key, provider=args.provider, endpoint=args.endpoint)
    before = snapshot(args.workspace)
    manifest: dict[str, Any] = {
        "provider": args.provider,
        "scenario": args.scenario,
        "model": args.model,
        "effort": args.effort,
        "budgets": {"max_calls": args.max_calls, "max_tokens": args.max_tokens, "max_spend_usd": args.max_spend_usd},
        "credential_delivery": "temporary_grant",
        "virtual_key_policy": "cheap-experiments",
        "endpoint_origin": args.endpoint,
        "binary": binary,
        "launch_environment_allowlist": sanitize_environment(environment),
        "result": "inconclusive",
        "result_reason": "live scenario driver has not started",
    }
    bundle = CaptureBundle(args.artifact_dir, manifest)
    for frame in _initial_frames(args):
        bundle.append_json("scenario-actions.jsonl", {"action": "native_write_planned", "frame": frame})
    bundle.write_json("workspace-before.json", before)
    after = snapshot(args.workspace)
    bundle.write_json("workspace-after.json", after)
    bundle.write_json("workspace-diff.json", diff(before, after))
    bundle.write_json("assertions.json", {"result": "inconclusive", "assertions": []})
    bundle.write_summary("# Native harness capture\n\nThe bundle was initialized before launching a live scenario.\n")
    bundle.finalize()
    # Deliberately drop the in-memory key before returning; it was never serialized.
    del key
    return args.artifact_dir


def main() -> int:
    args = _parser().parse_args()
    try:
        location = run(args)
    except (FileNotFoundError, ValueError) as error:
        print(f"capture refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"artifact_dir": str(location), "status": "initialized"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
