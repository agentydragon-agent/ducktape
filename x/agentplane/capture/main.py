"""Opt-in live native-wire capture runner.

This runner refuses implicit model/budget/credential choices. Offline replay does not
invoke it and never needs a harness binary, network, or credential.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Any
from urllib.parse import urlsplit

from x.agentplane.capture.artifacts import CaptureBundle
from x.agentplane.capture.binary_resolution import resolve_binary
from x.agentplane.capture.credential_boundary import credential_environment, read_runtime_key, sanitize_environment
from x.agentplane.capture.llm_recording_proxy import BudgetExceededError, recording_proxy
from x.agentplane.capture.providers.claude import scenarios as claude_scenarios
from x.agentplane.capture.providers.codex import scenarios as codex_scenarios
from x.agentplane.capture.providers.shared_capture import NativeCapture
from x.agentplane.capture.records import b64, json_wrapper, sha256
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
    if args.scenario not in {"launch_handshake", "baseline"}:
        raise ValueError(f"live scenario driver not yet implemented: {args.provider}/{args.scenario}")
    if args.scenario == "baseline" and args.max_calls < 1:
        raise ValueError("baseline requires at least one allowed provider call")
    if not args.workspace.is_dir():
        raise ValueError("workspace must already be a fresh synthetic directory")
    if args.artifact_dir.exists():
        raise ValueError("artifact directory must not exist")


def _command(args: argparse.Namespace, binary: dict[str, Any], *, endpoint: str) -> list[str]:
    executable = binary["resolved_path"]
    if args.provider == "claude":
        return claude_scenarios.command(executable, model=args.model)
    return codex_scenarios.command(executable, endpoint=endpoint)


def _handshake(args: argparse.Namespace, capture: NativeCapture) -> dict[str, Any]:
    if args.provider == "claude":
        return claude_scenarios.launch_handshake(capture)
    return codex_scenarios.launch_handshake(capture, cwd=str(args.workspace), model=args.model, effort=args.effort)


def _baseline(args: argparse.Namespace, capture: NativeCapture, handshake: dict[str, Any]) -> dict[str, Any]:
    if args.provider == "claude":
        return claude_scenarios.baseline(capture)
    started = handshake["thread_start_response"]
    assert isinstance(started, dict)
    return codex_scenarios.baseline(capture, thread_start_response=started)


def _start_recording_proxy(bundle: CaptureBundle, upstream: str, *, max_calls: int) -> tuple[Any, Thread, str]:
    """Start a loopback, header-blind proxy and return its path-preserving base URL."""

    calls = 0

    def record(kind: str, event: dict[str, Any]) -> None:
        nonlocal calls
        if kind == "request":
            calls += 1
            if calls > max_calls:
                raise BudgetExceededError("capture provider-call ceiling exceeded")
        body = event.pop("body", b"")
        payload = {
            **event,
            "body_base64": b64(body),
            "byte_length": len(body),
            "sha256": sha256(body),
            "parsed": json_wrapper(body),
        }
        filename = {
            "request": "llm-requests.jsonl",
            "response_chunk": "llm-response-chunks.jsonl",
            "response": "llm-responses.jsonl",
            "proxy_error": "llm-responses.jsonl",
        }[kind]
        bundle.append_json(filename, payload)
        if kind == "request":
            bundle.append_json(
                "correlation.jsonl",
                {
                    "capture_request_id": event["capture_request_id"],
                    "basis": "sole_active_native_execution_in_process_generation_1",
                },
            )

    server = recording_proxy(upstream=upstream, record=record)
    thread = Thread(target=server.serve_forever, name="agentplane-llm-recorder", daemon=True)
    thread.start()
    path = urlsplit(upstream).path.rstrip("/")
    return server, thread, f"http://127.0.0.1:{server.server_port}{path}"


def run(args: argparse.Namespace) -> Path:
    _validate(args)
    require_scenario(args.provider, args.scenario)
    binary = resolve_binary(args.provider, getattr(args, f"{args.provider}_bin"))
    key = read_runtime_key(args.credential_file)
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
        "result": "inconclusive",
        "result_reason": "not_started",
    }
    bundle = CaptureBundle(args.artifact_dir, manifest)
    proxy = None
    proxy_thread = None
    harness_endpoint = args.endpoint
    if args.scenario == "baseline":
        proxy, proxy_thread, harness_endpoint = _start_recording_proxy(bundle, args.endpoint, max_calls=args.max_calls)
        bundle.manifest["recording_proxy"] = {"upstream_origin": args.endpoint, "endpoint": harness_endpoint}
    provider_environment = credential_environment(key=key, provider=args.provider, endpoint=harness_endpoint)
    bundle.manifest["launch_environment_allowlist"] = sanitize_environment(provider_environment)
    capture = NativeCapture(
        bundle,
        _command(args, binary, endpoint=harness_endpoint),
        cwd=args.workspace,
        environment={**os.environ, **provider_environment},
    )
    result: dict[str, Any]
    try:
        capture.start()
        result = {"handshake": _handshake(args, capture)}
        if args.scenario == "baseline":
            result["baseline"] = _baseline(args, capture, result["handshake"])
        bundle.manifest["result"] = "pass"
        bundle.manifest["result_reason"] = "native_scenario_observed"
    except Exception as error:
        result = {"error_kind": type(error).__name__}
        bundle.manifest["result"] = "fail"
        bundle.manifest["result_reason"] = type(error).__name__
        raise
    finally:
        exit_code = capture.close()
        if proxy is not None:
            proxy.shutdown()
            assert proxy_thread is not None
            proxy_thread.join(timeout=10)
        after = snapshot(args.workspace)
        bundle.write_json("workspace-before.json", before)
        bundle.write_json("workspace-after.json", after)
        bundle.write_json("workspace-diff.json", diff(before, after))
        bundle.write_json(
            "assertions.json", {"result": bundle.manifest["result"], "evidence": result if "result" in locals() else {}}
        )
        bundle.write_summary(f"# Native harness capture\n\nResult: `{bundle.manifest['result']}`.\n")
        bundle.manifest["process_exit_code"] = exit_code
        bundle.finalize()
        del key
    return args.artifact_dir


def main() -> int:
    args = _parser().parse_args()
    try:
        location = run(args)
    except (FileNotFoundError, ValueError, TimeoutError, OSError) as error:
        print(f"capture refused or failed: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({"artifact_dir": str(location), "status": "complete"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
