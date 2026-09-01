"""Record small, direct Claude/Codex protocol examples.

This is deliberately a discovery script: it writes raw JSONL pipes and LiteLLM bodies,
not a general runner, fixture framework, or provider-neutral API.
"""

from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from x.agentplane.capture.llm_recording_proxy import recording_proxy
from x.agentplane.capture.providers.claude import scenarios as claude
from x.agentplane.capture.providers.codex import scenarios as codex
from x.agentplane.capture.providers.shared_capture import NativeCapture, write_jsonl
from x.agentplane.capture.records import CaptureMetadata, ProxyErrorRecord, RequestRecord, ResponseChunkRecord
from x.agentplane.capture.replay import ReplayServer, serve

SCENARIOS = ("launch", "baseline", "shell", "file_edits", "steering", "second_input", "interrupt", "idle_resume")


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
    result.add_argument("--replay-from", type=Path, help="serve saved LiteLLM bodies instead of calling --endpoint")
    return result


def _key(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise ValueError("credential file must be 0600")
    return path.read_text().strip()


def _prepare(workspace: Path) -> None:
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Both native harnesses require their explicitly isolated state roots to exist.
    (workspace / ".claude").mkdir(mode=0o700)
    (workspace / ".codex").mkdir(mode=0o700)
    (workspace / "editable.txt").write_text("before\n")


def _proxy(output: Path, upstream: str, provider: str, replay_from: Path | None) -> tuple[ThreadingHTTPServer, str]:
    def record(event: RequestRecord | ResponseChunkRecord | ProxyErrorRecord) -> None:
        write_jsonl(
            output / ("llm-requests.jsonl" if isinstance(event, RequestRecord) else "llm-responses.jsonl"), event
        )

    server = ReplayServer(replay_from) if replay_from else recording_proxy(upstream=upstream, record=record)
    origin = f"http://127.0.0.1:{server.server_port}"
    return server, origin if provider == "claude" else origin + urlsplit(upstream).path.rstrip("/")


def _command(provider: str, binary: str, model: str, endpoint: str, *, resume_id: str | None = None) -> list[str]:
    return (
        claude.command(binary, model=model, resume_id=resume_id)
        if provider == "claude"
        else codex.command(binary, endpoint=endpoint)
    )


def _prompt(scenario: str) -> str:
    return {
        "baseline": "Reply with exactly: CAPTURE_BASELINE_OK",
        "shell": (
            "Use shell to run `printf 'PROBE_STDOUT\\n'` and "
            '`sh -c \'printf "probe stdout before failure\\n"; '
            'printf "probe stderr before failure\\n" >&2; exit 23\'`; report outcomes.'
        ),
        "file_edits": "Read editable.txt, change it to exactly `after\\n`, reread it, then reply FILE_EDIT_DONE.",
    }[scenario]


def run(args: argparse.Namespace) -> None:
    if args.output.exists():
        raise ValueError("output must not exist")
    _prepare(args.workspace)
    args.output.mkdir(mode=0o700)
    for name in ("stdin.jsonl", "stdout.jsonl", "stderr.jsonl", "llm-requests.jsonl", "llm-responses.jsonl"):
        (args.output / name).touch(mode=0o600)
    key = _key(args.credential_file)
    proxy, proxy_endpoint = _proxy(args.output, args.endpoint, args.provider, args.replay_from)
    environment = {**os.environ}
    if args.provider == "claude":
        environment.update(
            {
                "ANTHROPIC_AUTH_TOKEN": key,
                "ANTHROPIC_BASE_URL": proxy_endpoint,
                "CLAUDE_CONFIG_DIR": str(args.workspace / ".claude"),
            }
        )
    else:
        environment.update(
            {"OPENAI_API_KEY": key, "OPENAI_BASE_URL": proxy_endpoint, "CODEX_HOME": str(args.workspace / ".codex")}
        )

    def start_capture(*, resume_id: str | None = None) -> NativeCapture:
        return NativeCapture(
            args.output,
            _command(args.provider, args.binary, args.model, proxy_endpoint, resume_id=resume_id),
            cwd=args.workspace,
            environment=environment,
        )

    with serve(proxy):
        with start_capture() as capture:
            handshake = (
                claude.launch_handshake(capture)
                if args.provider == "claude"
                else codex.launch_handshake(
                    capture,
                    cwd=str(args.workspace),
                    model=args.model,
                    effort="low",
                    persist=args.scenario == "idle_resume",
                )
            )
            if args.scenario in {"baseline", "shell", "file_edits"}:
                if args.provider == "claude":
                    claude.submit(capture, _prompt(args.scenario))
                else:
                    codex.submit(
                        capture, thread_start_response=handshake["thread_start_response"], text=_prompt(args.scenario)
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
            elif args.scenario == "idle_resume":
                if args.provider == "claude":
                    initial = claude.submit(capture, "Reply with exactly: IDLE_RESUME_SEED_OK")
                    resume_id = claude.session_id(initial)
                else:
                    initial = codex.submit(
                        capture,
                        thread_start_response=handshake["thread_start_response"],
                        text="Reply with exactly: IDLE_RESUME_SEED_OK",
                    )
                    thread_id = initial["thread_id"]
        if args.scenario == "idle_resume":
            with start_capture(resume_id=resume_id if args.provider == "claude" else None) as capture:
                if args.provider == "claude":
                    claude.launch_handshake(capture)
                    claude.submit(capture, "Reply with exactly: IDLE_RESUME_OK")
                else:
                    codex.resume_handshake(capture, thread_id=thread_id)
                    codex.submit_to_thread(
                        capture, thread_id=thread_id, request_id="capture-6", text="Reply with exactly: IDLE_RESUME_OK"
                    )
        if args.replay_from:
            assert isinstance(proxy, ReplayServer)
            proxy.assert_consumed()
        (args.output / "metadata.json").write_text(
            CaptureMetadata(provider=args.provider, scenario=args.scenario, model=args.model).model_dump_json() + "\n"
        )


def main() -> None:
    run(parser().parse_args())


if __name__ == "__main__":
    main()
