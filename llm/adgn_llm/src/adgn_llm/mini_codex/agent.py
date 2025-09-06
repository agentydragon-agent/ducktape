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
from openai.types.shared_params import Reasoning as ReasoningParams, ReasoningEffort


from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .mcp_manager import McpManager
from .loggers import TranscriptLogger


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
        blocks = [
            b.model_dump(by_alias=True) for b in (getattr(res, "content", []) or [])
        ]
        return json.dumps({"content": blocks})
    except Exception as e:  # pragma: no cover
        return json.dumps({"error": f"conversion_error: {e}"})


def _is_reasoning_item(item: Any) -> bool:
    return (
        isinstance(item, ResponseReasoningItem)
        or getattr(item, "type", None) == "reasoning"
    )


# Namespaced tool form: mcp__{server}__{tool}
ToolMap = dict[str, Any]

SYSTEM_INSTRUCTIONS = "You are a code agent. Be concise."


_logger = structlog.get_logger("mini_codex.setup")


def _openai_client() -> openai.OpenAI:
    return openai.OpenAI()




@retry(
    retry=retry_if_exception(
        lambda e: isinstance(
            e, APITimeoutError | APIConnectionError | RateLimitError | APIStatusError,
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
        require_at_least_one_tool: bool,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        mcp: McpManager,
        client: openai.OpenAI,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: Literal["auto", "concise", "detailed"] | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._model = model
        self._system = system or SYSTEM_INSTRUCTIONS
        self._require_one_tool = require_at_least_one_tool
        self._on_event = on_event or (lambda _evt: None)
        self._mcp = mcp
        self._client = client
        self._agent_name = agent_name or "mini_codex"
        self._transcript: list[TranscriptItem] = []
        self._reasoning_effort = reasoning_effort
        self._reasoning_summary = reasoning_summary
        self._metrics = Metrics()
        self._log = structlog.get_logger("mini_codex").bind(
            component="MiniCodex", model=self._model,
        )
        # Logging artifacts
        self._log_dir: Path | None = None
        self._transcript_jsonl: Path | None = None

    @classmethod
    async def start(  # noqa: PLR0913
        cls,
        *,
        model: str,
        tools: ToolMap,
        system: str | None = None,
        require_at_least_one_tool: bool = True,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        client: openai.OpenAI,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: Literal["auto", "concise", "detailed"] | None = None,
    ) -> MiniCodex:
        mcp = await McpManager.from_servers(servers_cfg=tools, inproc_sessions=None)
        inst = cls(
            model=model,
            system=system,
            require_at_least_one_tool=require_at_least_one_tool,
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
        # Keep a run.json for quick metadata
        meta = {
            "model": self._model,
            "agent_name": self._agent_name,
            "ts": int(time.time()),
            "pid": os.getpid(),
        }
        (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def tools(self) -> list[dict[str, Any]]:
        return self._mcp.list_tools()

    def _emit_event(self, evt: dict[str, Any]) -> None:
        self._log.info("mini_codex_event", **evt)
        self._on_event(evt)

    def _log_event(self, evt: dict[str, Any]) -> None:
        # 1) Emit via structlog
        self._log.info("mini_codex_event", **evt)
        # 2) Append to transcript.jsonl to mirror the conversation progressively
        if self._transcript_jsonl is not None:
            with self._transcript_jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(evt, ensure_ascii=False) + "\n")

    @property
    def messages(self) -> list[dict[str, Any]]:
        return dump_messages_for_api(self._transcript)

    async def run(
        self, user_text: str, stream: bool = False,
    ) -> AgentResult | AsyncIterator[dict[str, Any]]:
        if stream:

            async def _gen() -> AsyncIterator[dict[str, Any]]:
                res = await self.run(user_text, stream=False)  # type: ignore[assignment]
                yield {"kind": "final", "result": res}

            return _gen()

        self._transcript.append(UserMessage(role="user", content=user_text))
        self._emit_event({"kind": "user_text", "text": user_text})
        sequence: list[dict[str, Any]] = []
        assistant_text_chunks: list[str] = []
        have_used_tool = False

        while True:
            instructions = self._system
            extra = self._mcp.instruction_block()
            if extra:
                instructions = f"{instructions}\n\n{extra}"

            # Always send the full transcript each turn (no deltas)
            input_payload = dump_messages_for_api(self._transcript)

            # Per Responses API: accepted values include "auto", "none", "required",
            # or a specific function name via {"type":"function","function":{"name":"..."}}
            tool_choice_value: str | dict[str, Any] = (
                "required" if (self._require_one_tool and not have_used_tool) else "auto"
            )

            reasoning_kwargs: dict[str, Any] = {}
            if self._reasoning_effort is not None or self._reasoning_summary is not None:
                reasoning_kwargs = {
                    "reasoning": cast(ReasoningParams, {
                        "effort": self._reasoning_effort,
                        "summary": self._reasoning_summary,
                    }),
                }
            resp = _responses_create_with_retry(
                self._client,
                model=self._model,
                input=input_payload,
                instructions=instructions,
                stream=False,
                tool_choice=tool_choice_value,
                store=True,
                tools=self._mcp.list_tools(),
                **reasoning_kwargs,
            )

            requires: list[ResponseFunctionToolCall] = []
            reasoning_count = 0
            for item in resp.output:
                if _is_reasoning_item(item):
                    self._transcript.append(item.model_dump(exclude_none=True))
                    reasoning_count += 1
                elif isinstance(item, ResponseOutputMessage):
                    parts = [
                        part.text
                        for part in item.content
                        if isinstance(part, ResponseOutputText) and part.text
                    ]
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
                dbg = [
                    {"name": tc.name, "call_id": tc.call_id, "arguments": tc.arguments}
                    for tc in requires
                ]
                self._log.debug(
                    "tool_calls", count=len(dbg), reasoning_items=reasoning_count,
                )

            if not requires:
                break

            for fc in requires:
                args = json.loads(fc.arguments) if fc.arguments else {}
                if not isinstance(args, dict):
                    args = {}
                server, tool_name = self._mcp.resolve_function(fc.name)
                session = self._mcp.get_session(server)
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
                        has_structured=getattr(res_ct, "structuredContent", None)
                        is not None,
                        blocks=len(getattr(res_ct, "content", []) or []),
                        is_error=bool(getattr(res_ct, "isError", False)),
                        latency_ms=int(latency * 1000),
                    )
                self._emit_event(call_evt)
                out_str = _responses_output_from_calltool(res_ct)
                fco = FunctionCallOutput(
                    type="function_call_output", call_id=fc.call_id, output=out_str,
                )
                sequence.append(
                    {
                        "kind": "function_call_output",
                        **fco.model_dump(exclude_none=True),
                    },
                )
                self._transcript.append(fco)

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
                    "metrics": {"turns": self._metrics.turns, "tool_calls": self._metrics.tool_calls},
                }
                transcript_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return AgentResult(text=text, sequence=sequence, metrics=self._metrics)

    async def close(self) -> None:
        await self._mcp.close()


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


