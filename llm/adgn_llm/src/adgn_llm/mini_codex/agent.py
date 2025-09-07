"""
MiniCodex agent built on OpenAI Responses API with direct MCP tool wiring.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import openai
import structlog
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

# Reasoning output blocks from Responses API
try:
    from openai.types.responses import ResponseReasoningItem
except Exception:  # pragma: no cover

    class ResponseReasoningItem:  # type: ignore[no-redef]
        ...


# Typed request params for reasoning
from openai.types.shared_params import Reasoning as ReasoningParams
from openai.types.shared_params import ReasoningEffort
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .loggers import TranscriptLogger
from .mcp_manager import McpManager


@dataclass
class AgentResult:
    text: str
    sequence: list[dict[str, Any]]
    metrics: Metrics


class Metrics:
    def __init__(self) -> None:
        self.turns = 0
        self.tool_calls = 0


def _responses_output_from_calltool(res: Any) -> str:
    try:
        structured = getattr(res, "structuredContent", None)
        if structured is not None:
            return json.dumps(structured)
        blocks = [b.model_dump(by_alias=True) for b in (getattr(res, "content", []) or [])]
        return json.dumps({"content": blocks})
    except Exception as e:  # pragma: no cover
        return json.dumps({"error": f"conversion_error: {e}"})


def _is_reasoning_item(item: Any) -> bool:
    return isinstance(item, ResponseReasoningItem) or getattr(item, "type", None) == "reasoning"


# Namespaced tool form: mcp__{server}__{tool}
ToolMap = dict[str, Any]

SYSTEM_INSTRUCTIONS = "You are a code agent. Be concise."


_logger = structlog.get_logger("mini_codex.setup")


def _openai_client() -> openai.OpenAI:
    return openai.OpenAI()


@retry(
    retry=retry_if_exception(
        lambda e: isinstance(
            e,
            APITimeoutError | APIConnectionError | RateLimitError | APIStatusError,
        ),
    ),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(4),
)
def _responses_create_with_retry(client: openai.OpenAI, **kwargs: Any):
    """Wrapper around client.responses.create with retry for transient errors."""
    return client.responses.create(**kwargs)


def load_mcp_file(path: str) -> ToolMap:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    servers = data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        raise ValueError(".mcp.json: mcpServers must be object")
    return dict(servers)


class MiniCodex:
    def __init__(  # noqa: PLR0913
        self,
        *,
        model: str,
        system: str | None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        mcp: McpManager,
        client: openai.OpenAI,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: Literal["auto", "concise", "detailed"] | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._model = model
        self._system = system or SYSTEM_INSTRUCTIONS
        self._on_event = on_event or (lambda _evt: None)
        self._mcp = mcp
        self._client = client
        self._agent_name = agent_name or "mini_codex"
        self._transcript: list[TranscriptItem] = []
        self._reasoning_effort = reasoning_effort
        self._reasoning_summary = reasoning_summary
        self._metrics = Metrics()
        self._log = structlog.get_logger("mini_codex").bind(
            component="MiniCodex",
            model=self._model,
        )
        # Logging artifacts
        self._log_dir: Path | None = None
        self._transcript_jsonl: Path | None = None
        # Notification plumbing; client can set a handler and decide when to sample
        self._notification_handler: Callable[[dict[str, Any]], None] = lambda _evt: None
        self._pending_system_notes: list[str] = []
        self._busy: bool = False
        self._run_require_one_tool: bool | None = None

    def set_notification_handler(self, handler: Callable[[dict[str, Any]], None]) -> None:
        """Install a notification handler the host can use to react (e.g., autosample).

        Handler is invoked with a dict event. The host decides whether/when to call
        `await agent.sample()`; MiniCodex itself does not auto-sample.
        """
        self._notification_handler = handler

    def inject_system_message(self, text: str) -> None:
        """Append a system message at the current end of transcript (temporal order)."""
        msg = {"role": "system", "content": text}
        self._transcript.append(msg)
        self._emit_event({"kind": "system_note", "text": text})

    def notify(self, evt: dict[str, Any]) -> None:
        """Receive external notifications (e.g., MCP resource updates).

        - If busy (mid-turn), buffer as system notes to inject before next sampling.
        - If idle, inject immediately to preserve temporal order.
        - Always forward to the installed notification handler for host-driven autosampling.
        """
        text = (
            (evt.get("text") if isinstance(evt, dict) else None)
            or (evt.get("message") if isinstance(evt, dict) else None)
            or json.dumps(evt, ensure_ascii=False)
        )
        if self._busy:
            self._pending_system_notes.append(text)
        else:
            self.inject_system_message(text)
        self._notification_handler(evt)

    async def sample(self, require_at_least_one_tool: bool | None = None) -> AgentResult:
        """Run a single model turn using the existing transcript (no new user message)."""
        self._run_require_one_tool = True if require_at_least_one_tool is None else require_at_least_one_tool
        return await self._single_turn()

    async def _single_turn(self) -> AgentResult:
        sequence: list[dict[str, Any]] = []
        assistant_text_chunks: list[str] = []
        have_used_tool = False

        self._busy = True
        while True:
            if self._pending_system_notes:
                for _note in self._pending_system_notes:
                    self.inject_system_message(_note)
                self._pending_system_notes.clear()
            instructions = self._system
            input_payload = dump_messages_for_api(self._transcript)

            tool_choice_value: str | dict[str, Any] = (
                "required" if (((self._run_require_one_tool if self._run_require_one_tool is not None else True)) and not have_used_tool) else "auto"
            )

            reasoning_kwargs: dict[str, Any] = {}
            if self._reasoning_effort is not None or self._reasoning_summary is not None:
                reasoning_kwargs = {
                    "reasoning": cast(
                        ReasoningParams,
                        {
                            "effort": self._reasoning_effort,
                            "summary": self._reasoning_summary,
                        },
                    ),
                }
            # Per-server MCP resource FYI (max 5 URIs per server)
            try:
                resources = await self._mcp.list_resources()
            except Exception:
                resources = []
            by_server: dict[str, list[str]] = {}
            for it in resources:
                s = it.get("server")
                u = it.get("uri")
                if s and isinstance(u, str):
                    by_server.setdefault(s, []).append(u)
            if by_server:
                lines: list[str] = []
                for s, uris in by_server.items():
                    first = uris[:5]
                    more = max(0, len(uris) - len(first))
                    if more:
                        lines.append(f"server={s} resources: {first} (+{more} more; list via mcp__resources__list)")
                    else:
                        lines.append(f"server={s} resources: {first}")
                instructions = f"{instructions}\n\nFYI: MCP resources available:\n- " + "\n- ".join(lines)

            tools_list = await self._mcp.list_tools()
            tools_list.extend(self._resource_tools_descriptors())

            resp = _responses_create_with_retry(
                self._client,
                model=self._model,
                input=input_payload,
                instructions=instructions,
                stream=False,
                tool_choice=tool_choice_value,
                store=True,
                tools=tools_list,
                **reasoning_kwargs,
            )

            requires: list[ResponseFunctionToolCall] = []
            reasoning_count = 0
            for item in resp.output:
                if _is_reasoning_item(item):
                    self._transcript.append(item.model_dump(exclude_none=True))
                    reasoning_count += 1
                elif isinstance(item, ResponseOutputMessage):
                    parts = [part.text for part in item.content if isinstance(part, ResponseOutputText) and part.text]
                    if parts:
                        combined = "\n".join(parts)
                        assistant_text_chunks.append(combined)
                        msg = AssistantMessage(role="assistant", content=combined)
                        self._transcript.append(msg)
                        evt = {"kind": "assistant_text", "text": combined}
                        sequence.append(evt)
                        self._emit_event(evt)
                elif isinstance(item, ResponseFunctionToolCall):
                    requires.append(item)
                    # Persist tool call into transcript so the next turn has full context
                    self._transcript.append(item.model_dump(exclude_none=True))

            if os.environ.get("MINICODEX_DEBUG"):
                dbg = [{"name": tc.name, "call_id": tc.call_id, "arguments": tc.arguments} for tc in requires]
                self._log.debug(
                    "tool_calls",
                    count=len(dbg),
                    reasoning_items=reasoning_count,
                )

            if not requires:
                break

            for fc in requires:
                args = json.loads(fc.arguments) if fc.arguments else {}
                if not isinstance(args, dict):
                    args = {}

                # Built-in resource tools
                if fc.name == "mcp__resources__list":
                    server_filter = args.get("server")
                    uri_prefix = args.get("uri_prefix")
                    items = await self._mcp.list_resources(only=[server_filter] if server_filter else None)
                    if uri_prefix:
                        items = [it for it in items if isinstance(it.get("uri"), str) and it["uri"].startswith(uri_prefix)]
                    out_str = json.dumps({"resources": items}, ensure_ascii=False)
                    call_evt = {"kind": "tool_call", "name": fc.name, "args": args, "call_id": fc.call_id}
                    sequence.append(call_evt)
                    self._emit_event(call_evt)
                    fco = FunctionCallOutput(type="function_call_output", call_id=fc.call_id, output=out_str)
                    fco_evt = {"kind": "function_call_output", **fco.model_dump(exclude_none=True)}
                    sequence.append(fco_evt)
                    self._transcript.append(fco)
                    self._emit_event(fco_evt)
                    continue

                if fc.name == "mcp__resources__read":
                    server = args.get("server")
                    uri = args.get("uri")
                    start_offset = int(args.get("start_offset", 0))
                    if "max_bytes" not in args:
                        raise ValueError("max_bytes is required for mcp__resources__read")
                    max_bytes = int(args.get("max_bytes"))
                    if not isinstance(server, str) or not isinstance(uri, str):
                        raise ValueError("server and uri are required and must be strings")
                    res = await self._mcp.read_resource(server, uri)
                    mime = getattr(res, "mimeType", None) or getattr(res, "mime", None)
                    contents = getattr(res, "contents", None) or []
                    text_slice: str | None = None
                    base64_data: str | None = None
                    total_bytes: int | None = None
                    if contents:
                        part = contents[0]
                        t = getattr(part, "text", None)
                        if isinstance(t, str):
                            full_bytes = t.encode("utf-8")
                            total_bytes = len(full_bytes)
                            chunk = full_bytes[start_offset : start_offset + max_bytes]
                            text_slice = chunk.decode("utf-8", errors="replace")
                        else:
                            data_b64 = getattr(part, "data", None) or getattr(part, "base64", None)
                            if isinstance(data_b64, str):
                                total_bytes = len(data_b64)
                                base64_data = data_b64[start_offset : start_offset + max_bytes]
                    payload = {
                        "mime": mime,
                        "start_offset": start_offset,
                        "max_bytes": max_bytes,
                        "total_bytes": total_bytes,
                        "text": text_slice,
                        "base64": base64_data,
                    }
                    out_str = json.dumps(payload, ensure_ascii=False)
                    call_evt = {"kind": "tool_call", "name": fc.name, "args": args, "call_id": fc.call_id}
                    sequence.append(call_evt)
                    self._emit_event(call_evt)
                    fco = FunctionCallOutput(type="function_call_output", call_id=fc.call_id, output=out_str)
                    fco_evt = {"kind": "function_call_output", **fco.model_dump(exclude_none=True)}
                    sequence.append(fco_evt)
                    self._transcript.append(fco)
                    self._emit_event(fco_evt)
                    continue

                # Namespaced MCP tool
                server, tool_name = self._mcp.resolve_function(fc.name)
                session = await self._mcp.get_session(server)
                start = time.perf_counter()
                res_ct = await session.call_tool(name=tool_name, arguments=args)
                latency = time.perf_counter() - start
                call_evt = {
                    "kind": "tool_call",
                    "name": fc.name,
                    "args": args,
                    "call_id": fc.call_id,
                }
                sequence.append(call_evt)
                if os.environ.get("MINICODEX_DEBUG"):
                    self._log.debug(
                        "tool_result",
                        name=fc.name,
                        args=args,
                        has_structured=getattr(res_ct, "structuredContent", None) is not None,
                        blocks=len(getattr(res_ct, "content", []) or []),
                        is_error=bool(getattr(res_ct, "isError", False)),
                        latency_ms=int(latency * 1000),
                    )
                self._emit_event(call_evt)
                out_str = _responses_output_from_calltool(res_ct)
                fco = FunctionCallOutput(
                    type="function_call_output",
                    call_id=fc.call_id,
                    output=out_str,
                )
                fco_evt = {"kind": "function_call_output", **fco.model_dump(exclude_none=True)}
                sequence.append(fco_evt)
                self._transcript.append(fco)
                self._emit_event(fco_evt)
                is_err = bool(getattr(res_ct, "isError", False))
                parsed_error: str | None = None
                try:
                    data = json.loads(out_str)
                    if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), str):
                        parsed_error = data.get("error")
                except Exception:
                    parsed_error = None
                if is_err or parsed_error is not None:
                    err_evt = {"kind": "tool_error", "name": fc.name, "call_id": fc.call_id}
                    if parsed_error:
                        err_evt["error"] = parsed_error
                    sequence.append(err_evt)
                    self._emit_event(err_evt)

            self._metrics.tool_calls += len(requires)
            have_used_tool = True

        self._metrics.turns += 1
        text = "\n".join(assistant_text_chunks)
        # Persist transcript and sequence to logs if configured
        try:
            if self._log_dir is not None:
                transcript_path = self._log_dir / "transcript.json"
                payload = {
                    "transcript": dump_messages_for_api(self._transcript),
                    "sequence": sequence,
                    "metrics": {
                        "turns": self._metrics.turns,
                        "tool_calls": self._metrics.tool_calls,
                    },
                }
                transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            self._log.exception("transcript_write_failed")
            raise
        finally:
            self._busy = False
        return AgentResult(text=text, sequence=sequence, metrics=self._metrics)

    def _resource_tools_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "mcp__resources__list",
                "description": "List MCP resources (optionally filter by server and uri prefix)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string"},
                        "uri_prefix": {"type": "string"},
                    },
                },
            },
            {
                "type": "function",
                "name": "mcp__resources__read",
                "description": "Read a resource with byte windowing",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "server": {"type": "string"},
                        "uri": {"type": "string"},
                        "start_offset": {"type": "integer", "default": 0},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["server", "uri", "max_bytes"],
                },
            },
        ]

    @classmethod
    async def create(  # noqa: PLR0913
        cls,
        *,
        model: str,
        mcp: McpManager,
        system: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        client: openai.OpenAI,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: Literal["auto", "concise", "detailed"] | None = None,
    ) -> MiniCodex:
        inst = cls(
            model=model,
            system=system,
            on_event=on_event,
            mcp=mcp,
            client=client,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
        )
        inst._init_logging()
        return inst

    def _init_logging(self) -> None:
        base = Path(os.environ.get("MINICODEX_LOG_DIR") or (Path.cwd() / "logs" / "mini_codex"))
        base.mkdir(parents=True, exist_ok=True)
        agent_dir = base / self._agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)
        run_dir = agent_dir / f"run_{int(time.time())}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        self._log_dir = run_dir
        # Announce log path for the run (stdout) and via structlog
        print(f"MiniCodex log dir: {run_dir}")
        self._log.info("mini_codex_log_dir", path=str(run_dir))
        # Attach JSONL transcript logger (always on)
        run_logger = TranscriptLogger(run_dir)
        prev_on_event = self._on_event

        def _chained(evt: dict[str, Any]) -> None:
            try:
                run_logger(evt)
            finally:
                prev_on_event(evt)

        self._on_event = _chained
        # Keep a run.json for quick metadata
        meta = {
            "model": self._model,
            "agent_name": self._agent_name,
            "ts": int(time.time()),
            "pid": os.getpid(),
        }
        (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _emit_event(self, evt: dict[str, Any]) -> None:
        self._log.info("mini_codex_event", **evt)
        self._on_event(evt)

    def _log_event(self, evt: dict[str, Any]) -> None:
        # Delegate to external transcript logger via _on_event
        self._emit_event(evt)

    @property
    def messages(self) -> list[dict[str, Any]]:
        return dump_messages_for_api(self._transcript)

    async def run(
        self,
        user_text: str,
        stream: bool = False,
        require_at_least_one_tool: bool | None = None,
    ) -> AgentResult | AsyncIterator[dict[str, Any]]:
        if stream:

            async def _gen() -> AsyncIterator[dict[str, Any]]:
                res = await self.run(user_text, stream=False, require_at_least_one_tool=require_at_least_one_tool)  # type: ignore[assignment]
                yield {"kind": "final", "result": res}

            return _gen()

        self._transcript.append(UserMessage(role="user", content=user_text))
        self._emit_event({"kind": "user_text", "text": user_text})
        self._run_require_one_tool = True if require_at_least_one_tool is None else require_at_least_one_tool
        result = await self._single_turn()
        return result

    async def __aenter__(self) -> "MiniCodex":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    # Back-compat: noop close
    async def close(self) -> None:
        return None


class UserMessage(BaseModel):
    role: Literal["user"]
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str


class FunctionCallOutput(BaseModel):
    type: Literal["function_call_output"]
    call_id: str
    output: str


Message = UserMessage | AssistantMessage | FunctionCallOutput
TranscriptItem = Message | dict[str, Any]


def dump_messages_for_api(messages: list[TranscriptItem]) -> list[dict[str, Any]]:
    """Format transcript for OpenAI Responses API.

    Accepts a mixed list of:
    - message dicts {"role": "user"|"assistant", "content": str}
    - reasoning items (dict with type="reasoning") — forwarded verbatim
    - function_call_output items: {"type": "function_call_output", "call_id": "...", "output": "..."}
    Note: We always send the full transcript each turn; do not send deltas.
    """
    out: list[dict[str, Any]] = []
    for item in messages:
        if isinstance(item, BaseModel):
            out.append(item.model_dump(exclude_none=True))
        elif isinstance(item, dict):
            out.append(dict(item))
        else:  # pragma: no cover
            raise TypeError(f"Unsupported transcript item type: {type(item)!r}")
    return out
