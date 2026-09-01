"""Record small, direct Claude/Codex protocol examples.

This is deliberately a discovery script: it writes raw JSONL pipes and LiteLLM bodies,
not a general runner, fixture framework, or provider-neutral API.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from x.agentplane.capture.llm_recording_proxy import recording_proxy
from x.agentplane.capture.providers.claude import scenarios as claude
from x.agentplane.capture.providers.codex import scenarios as codex
from x.agentplane.capture.providers.shared_capture import NativeCapture, raw, write_jsonl

SCENARIOS = ("launch", "baseline", "shell", "file_edits", "steering", "second_input", "interrupt")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--provider", choices=("claude", "codex"), required=True)
    result.add_argument("--scenario", choices=SCENARIOS, required=True)
    result.add_argument("--binary", required=True)
    result.add_argument("--model", required=True)
    result.add_argument("--endpoint", required=True)
    result.add_argument("--credential-file", type=Path, required=True)
    result.add_argument("--workspace", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def _key(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise ValueError("credential file must be 0600")
    return path.read_text().strip()


def _prepare(workspace: Path) -> None:
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__).with_name("fixtures") / "operation_probe.py", workspace / "operation_probe.py")
    (workspace / "editable.txt").write_text("before\n")


def _proxy(output: Path, upstream: str, provider: str) -> tuple[object, Thread, str]:
    def record(kind: str, event: dict[str, object]) -> None:
        body = event.pop("body", b"")
        assert isinstance(body, bytes)
        write_jsonl(
            output / ("llm-requests.jsonl" if kind == "request" else "llm-responses.jsonl"),
            {"kind": kind, **event, "body": raw(body)},
        )

    server = recording_proxy(upstream=upstream, record=record)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    return server, thread, origin if provider == "claude" else origin + urlsplit(upstream).path.rstrip("/")


def _command(provider: str, binary: str, model: str, endpoint: str) -> list[str]:
    return claude.command(binary, model=model) if provider == "claude" else codex.command(binary, endpoint=endpoint)


def _prompt(scenario: str) -> str:
    return {
        "baseline": "Reply with exactly: CAPTURE_BASELINE_OK",
        "shell": "Use shell to run `python operation_probe.py echo --value PROBE_STDOUT`, `python operation_probe.py fail`, and `python operation_probe.py count`; report outcomes.",
        "file_edits": "Read editable.txt, change it to exactly `after\\n`, reread it, then reply FILE_EDIT_DONE.",
    }[scenario]


def run(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError("output must not exist")
    _prepare(args.workspace)
    args.output.mkdir(mode=0o700)
    for name in (
        "stdin.jsonl",
        "stdout.jsonl",
        "stderr.jsonl",
        "actions.jsonl",
        "llm-requests.jsonl",
        "llm-responses.jsonl",
    ):
        (args.output / name).touch(mode=0o600)
    key = _key(args.credential_file)
    proxy, proxy_thread, proxy_endpoint = _proxy(args.output, args.endpoint, args.provider)
    environment = {**os.environ}
    if args.provider == "claude":
        environment.update({"ANTHROPIC_AUTH_TOKEN": key, "ANTHROPIC_BASE_URL": proxy_endpoint})
    else:
        environment.update({"OPENAI_API_KEY": key, "OPENAI_BASE_URL": proxy_endpoint})
    capture = NativeCapture(
        args.output,
        _command(args.provider, args.binary, args.model, proxy_endpoint),
        cwd=args.workspace,
        environment=environment,
    )
    try:
        capture.start()
        handshake = (
            claude.launch_handshake(capture)
            if args.provider == "claude"
            else codex.launch_handshake(capture, cwd=str(args.workspace), model=args.model, effort="low")
        )
        if args.scenario in {"baseline", "shell", "file_edits"}:
            if args.provider == "claude":
                claude.submit(capture, _prompt(args.scenario), action=f"claude_{args.scenario}")
            else:
                codex.submit(
                    capture,
                    thread_start_response=handshake["thread_start_response"],
                    text=_prompt(args.scenario),
                    action=f"codex_{args.scenario}",
                )
        elif args.scenario in {"steering", "second_input"}:
            if args.provider == "claude":
                claude.submit_while_active(
                    capture, scenario="steering" if args.scenario == "steering" else "normal_submit_while_active"
                )
            else:
                codex.submit_while_active(
                    capture,
                    thread_start_response=handshake["thread_start_response"],
                    scenario="steering" if args.scenario == "steering" else "normal_submit_while_active",
                )
        elif args.scenario == "interrupt":
            if args.provider == "claude":
                claude.interrupt(capture, with_queued_input=False)
            else:
                codex.interrupt(
                    capture, thread_start_response=handshake["thread_start_response"], with_queued_input=False
                )
        (args.output / "metadata.json").write_text(
            json.dumps({"provider": args.provider, "scenario": args.scenario, "model": args.model}) + "\n"
        )
    finally:
        capture.close()
        proxy.shutdown()
        proxy_thread.join(timeout=5)


def main() -> int:
    try:
        run(parser().parse_args())
    except (OSError, ValueError, TimeoutError) as error:
        print(f"capture failed: {type(error).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
