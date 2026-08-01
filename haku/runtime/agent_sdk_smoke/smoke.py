"""One-shot compatibility probe for subscription OAuth through the Agent SDK."""

import asyncio
import json
import os
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookInput,
    HookJSONOutput,
    HookMatcher,
    ResultMessage,
    TextBlock,
    __version__ as sdk_version,
)
from claude_agent_sdk._cli_version import __cli_version__ as cli_version
from claude_agent_sdk.types import HookEvent, StreamEvent

from haku.runtime.agent_sdk_transport.options import enable_fine_grained_streaming


def emit(event: str, **fields: Any) -> None:
    """Write one machine-readable diagnostic without serializing SDK objects."""
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def redact(text: str, secrets_to_hide: list[str]) -> str:
    """Remove known credentials from CLI stderr before logging it."""
    for value in secrets_to_hide:
        if value:
            text = text.replace(value, "[REDACTED]")
    return text


@dataclass
class HookCounts:
    user_prompt_submit: int = 0
    stop: int = 0
    pre_tool_use: int = 0


def make_hooks(counts: HookCounts) -> dict[HookEvent, list[HookMatcher]]:
    """Install observation hooks and a deny-all tool backstop."""

    async def observe(hook_input: HookInput, _tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        event = hook_input["hook_event_name"]
        if event == "UserPromptSubmit":
            counts.user_prompt_submit += 1
        elif event == "Stop":
            counts.stop += 1
        emit("hook", hook_event=event)
        return {}

    async def deny_tool(hook_input: HookInput, _tool_use_id: str | None, _context: HookContext) -> HookJSONOutput:
        counts.pre_tool_use += 1
        tool_name = hook_input.get("tool_name", "unknown")
        emit("unexpected_tool_attempt", tool_name=tool_name)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "The compatibility probe exposes no tools.",
            }
        }

    return {
        "UserPromptSubmit": [HookMatcher(hooks=[observe])],
        "Stop": [HookMatcher(hooks=[observe])],
        "PreToolUse": [HookMatcher(hooks=[deny_tool])],
    }


def sdk_environment() -> dict[str, str]:
    """Build only the telemetry overrides passed explicitly to the CLI."""
    run_id = os.environ["HAKU_AGENT_SDK_SMOKE_RUN_ID"]
    env = {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"],
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "cumulative",
        "OTEL_LOG_USER_PROMPTS": "1",
        "OTEL_LOG_TOOL_DETAILS": "1",
        "OTEL_LOG_TOOL_CONTENT": "1",
        "OTEL_LOG_RAW_API_BODIES": "1",
        # Kyverno's pod-wide NO_PROXY includes *.allegedly.works for internal
        # service ingress. Override it only for the CLI subprocess so the public
        # Alloy OTLP endpoint cannot bypass haku-sandbox's forced proxy.
        "NO_PROXY": (
            "127.0.0.1,localhost,*.forgejo,.forgejo,.svc,.svc.cluster.local,kubernetes.default.svc,10.0.0.0/8"
        ),
        "HAKU_AGENT_SDK_SMOKE_RUN_ID": run_id,
        "OTEL_RESOURCE_ATTRIBUTES": (f"service.name=haku-agent-sdk-smoke,haku.run_id={run_id}"),
    }
    bearer = os.environ.get("DUCKTAPE_OTEL_BEARER_TOKEN", "")
    if bearer:
        env["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Bearer%20{quote(bearer, safe='')}"
    return env


@dataclass
class TurnResult:
    text: str
    result: ResultMessage
    stream_events: int


async def run_turn(client: ClaudeSDKClient, prompt: str) -> TurnResult:
    """Send one turn and drain through its terminal ResultMessage."""
    await client.query(prompt)
    text_parts: list[str] = []
    result: ResultMessage | None = None
    stream_events = 0

    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            stream_events += 1
        elif isinstance(message, AssistantMessage):
            text_parts.extend(block.text for block in message.content if isinstance(block, TextBlock))
        elif isinstance(message, ResultMessage):
            result = message

    if result is None:
        raise RuntimeError("SDK response ended without a ResultMessage")
    if result.is_error:
        raise RuntimeError(
            f"SDK returned an error result: subtype={result.subtype!r} stop_reason={result.stop_reason!r}"
        )

    text = "".join(text_parts).strip() or (result.result or "").strip()
    emit(
        "turn_complete",
        duration_api_ms=result.duration_api_ms,
        duration_ms=result.duration_ms,
        is_error=result.is_error,
        num_turns=result.num_turns,
        session_id=result.session_id,
        stop_reason=result.stop_reason,
        stream_events=stream_events,
        subtype=result.subtype,
        total_cost_usd=result.total_cost_usd,
        usage=result.usage,
    )
    return TurnResult(text=text, result=result, stream_events=stream_events)


def find_transcript(config_dir: Path, session_id: str) -> Path:
    """Locate the SDK's disk-backed transcript without assuming cwd encoding."""
    matches = list(config_dir.glob(f"projects/**/{session_id}.jsonl"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one transcript for session {session_id}, found {len(matches)}")
    return matches[0]


def file_size(path: Path) -> int:
    """Keep blocking filesystem metadata access outside the async probe."""
    return path.stat().st_size


def make_stderr_logger(secrets_to_hide: list[str]) -> Callable[[str], None]:
    def log_stderr(line: str) -> None:
        emit("claude_cli_stderr", message=redact(line.rstrip(), secrets_to_hide))

    return log_stderr


def make_options(
    *, counts: HookCounts, cwd: Path, secrets_to_hide: list[str], resume: str | None = None
) -> ClaudeAgentOptions:
    """Construct identical fresh and resumed clients without loose kwargs."""
    return enable_fine_grained_streaming(
        ClaudeAgentOptions(
            cwd=cwd,
            env=sdk_environment(),
            hooks=make_hooks(counts),
            permission_mode="dontAsk",
            resume=resume,
            setting_sources=[],
            stderr=make_stderr_logger(secrets_to_hide),
            system_prompt=(
                "You are a deterministic compatibility probe. Never use tools. "
                "Follow output-format instructions exactly."
            ),
            tools=[],
        )
    )


async def probe(cwd: Path, config_dir: Path) -> None:
    oauth = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
    bearer = os.environ.get("DUCKTAPE_OTEL_BEARER_TOKEN", "")
    if oauth.startswith("REPLACE_WITH_"):
        raise RuntimeError("OAuth Secret still contains the committed placeholder")

    counts = HookCounts()
    secrets_to_hide = [oauth, bearer]

    emit(
        "probe_start",
        cli_version=cli_version,
        cwd=str(cwd),
        node_extra_ca_certs_present=bool(os.environ.get("NODE_EXTRA_CA_CERTS")),
        oauth_present=bool(oauth),
        proxy_present=bool(os.environ.get("HTTPS_PROXY")),
        run_id=os.environ["HAKU_AGENT_SDK_SMOKE_RUN_ID"],
        sdk_version=sdk_version,
        telemetry_bearer_present=bool(bearer),
    )

    nonce = secrets.token_hex(8)
    options = make_options(counts=counts, cwd=cwd, secrets_to_hide=secrets_to_hide)
    async with ClaudeSDKClient(options=options) as client:
        first = await run_turn(client, f"Reply with exactly: HELLO_FROM_HAKU {nonce}")
        if "HELLO_FROM_HAKU" not in first.text or nonce not in first.text:
            raise RuntimeError("first turn did not return the requested marker and nonce")
        if first.stream_events == 0:
            raise RuntimeError("partial-message streaming produced no StreamEvent")

        second = await run_turn(client, "Reply with only the nonce from my previous message.")
        if nonce not in second.text:
            raise RuntimeError("same-client second turn did not retain the nonce")
        session_id = second.result.session_id

    transcript = find_transcript(config_dir, session_id)
    emit("transcript_found", bytes=file_size(transcript), path=str(transcript))

    resume_options = make_options(counts=counts, cwd=cwd, secrets_to_hide=secrets_to_hide, resume=session_id)
    async with ClaudeSDKClient(options=resume_options) as resumed_client:
        resumed = await run_turn(resumed_client, "Reply with only the nonce from the first message in this session.")
    if nonce not in resumed.text:
        raise RuntimeError("disk-backed resumed session did not retain the nonce")
    if resumed.result.session_id != session_id:
        raise RuntimeError("resume silently started a different session despite using the same cwd")
    if counts.pre_tool_use:
        raise RuntimeError("Claude unexpectedly attempted to invoke a tool")

    emit("probe_passed", hooks=asdict(counts), session_id=session_id)


def main() -> None:
    cwd = Path(os.environ["HAKU_AGENT_SDK_SMOKE_CWD"]).resolve()
    config_dir = Path(os.environ["CLAUDE_CONFIG_DIR"]).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(probe(cwd, config_dir))
    except Exception as error:
        secrets_to_hide = [
            os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", ""),
            os.environ.get("DUCKTAPE_OTEL_BEARER_TOKEN", ""),
        ]
        emit("probe_failed", error=redact(str(error), secrets_to_hide), error_type=type(error).__name__)
        raise


if __name__ == "__main__":
    main()
