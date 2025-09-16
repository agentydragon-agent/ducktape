"""Stateless two-step continuation demos (text-only and tools).

This single example contains two short demos showing how to:
- Request 1 -> model emits reasoning + assistant-text
- Request 2 -> resend full prefix (prompt1, reasoning1, assistant1[, function_call]) plus prompt2
  so the model can continue statelessly (no previous_response_id)

Usage:
  export OPENAI_API_KEY=...
  python examples/stateless_two_step_demo.py [text|tools|both]

Notes:
- Uses model=gpt-5 with reasoning={'effort':'high'} by default.
- Keep examples small and self-contained for clarity.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from openai import OpenAI

API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    print("Please set OPENAI_API_KEY in the environment and re-run.")
    sys.exit(2)

client = OpenAI()
MODEL = os.environ.get("RESPONSES_TEST_MODEL", "gpt-5")

# Helper to normalize SDK items to plain dicts for printing/forwarding


def as_dict(it: Any) -> dict[str, Any]:
    # Require SDK items or plain dicts; return dicts unchanged and otherwise
    # use the SDK model_dump representation. Do not swallow AttributeError.
    if isinstance(it, dict):
        return it
    return it.model_dump(exclude_none=True)


# Helper to read item.type: prefer dict lookup for dicts and direct attribute access
# for SDK objects (do not use getattr or try/except that masks missing attributes)
def item_type(it: Any) -> Any:
    if isinstance(it, dict):
        return it.get("type")
    return it.type


# ---------- Text-only demo ----------


def run_text_demo() -> None:
    prompt1 = (
        "Please THINK step-by-step (emit your chain-of-thought as a reasoning item). "
        "After that reasoning, produce a short assistant-visible final message that says exactly: done1. "
        "Do NOT output only reasoning — the assistant-visible message must follow the reasoning."
    )
    prompt2 = "Now continue using prior context; briefly answer: second-step (include any further reasoning and assistant output)."

    print("\n--- TEXT DEMO: Request 1 (reasoning + assistant-text) ---")
    r1 = client.responses.create(
        model=MODEL, input=[{"role": "user", "content": prompt1}], reasoning={"effort": "high"}
    )
    out1 = r1.output or []
    print("Response 1 id:", r1.id)
    for it in out1:
        d = as_dict(it)
        print(" -", d.get("type") or type(it).__name__)
        print(json.dumps(d, indent=2, ensure_ascii=False))

    # Extract reasoning + assistant-visible message
    reasoning_items = [as_dict(it) for it in out1 if item_type(it) == "reasoning"]
    assistant_msgs = [as_dict(it) for it in out1 if item_type(it) == "message"]

    if not reasoning_items or not assistant_msgs:
        print(
            "WARNING: response1 missing reasoning or assistant message; demo will still attempt to replay what exists."
        )

    # Build stateless request2: reproduce prefix + prompt2
    input2 = [{"role": "user", "content": prompt1}]
    input2.extend(reasoning_items)
    input2.extend(assistant_msgs)
    input2.append({"role": "user", "content": prompt2})

    print("\n--- TEXT DEMO: Request 2 (stateless full-input) ---")
    r2 = client.responses.create(model=MODEL, input=input2, reasoning={"effort": "high"})
    out2 = r2.output or []
    print("Response 2 id:", r2.id)
    for it in out2:
        d = as_dict(it)
        print(" -", d.get("type") or type(it).__name__)
        print(json.dumps(d, indent=2, ensure_ascii=False))


# ---------- Tools demo ----------


def run_tools_demo() -> None:
    TOOLS = [
        {
            "name": "echo",
            "type": "function",
            "description": "Return the provided text",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        },
        {
            "name": "add",
            "type": "function",
            "description": "Add two numbers",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
            },
        },
    ]

    prompt1 = (
        "You MUST do in order: (1) THINK step-by-step and emit a reasoning item, "
        '(2) then emit a function_call with name \'echo\' and arguments {"text": "first"}, '
        "(3) do NOT output the tool result yourself."
    )
    prompt2 = "Now continue using prior context: after the tool result is provided, briefly answer 'second-step'."

    print("\n--- TOOLS DEMO: Request 1 (reasoning + function_call) ---")
    r1 = client.responses.create(
        model=MODEL,
        input=[{"role": "user", "content": prompt1}],
        tools=TOOLS,
        tool_choice="required",
        reasoning={"effort": "high"},
    )
    out1 = r1.output or []
    print("Response 1 id:", r1.id)
    for it in out1:
        d = as_dict(it)
        print(" -", d.get("type") or type(it).__name__)
        print(json.dumps(d, indent=2, ensure_ascii=False))

    # Extract pieces
    reasoning_items = [as_dict(it) for it in out1 if item_type(it) == "reasoning"]
    assistant_msgs = [as_dict(it) for it in out1 if item_type(it) == "message"]
    func_calls = [as_dict(it) for it in out1 if item_type(it) == "function_call"]

    if not func_calls:
        print("ERROR: model did not emit a function_call in request1; aborting tools demo.")
        return

    # Synthesize function_call_output(s) (simulate tool execution)
    fco_items = []
    for fc in func_calls:
        name = fc.get("name")
        args_raw = fc.get("arguments")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw or {}
        except Exception:
            args = {"_raw": args_raw}
        if name == "echo":
            tool_result = {"ok": True, "echo": args.get("text")}
        elif name == "add":
            tool_result = {"ok": True, "sum": args.get("a", 0) + args.get("b", 0)}
        else:
            tool_result = {"ok": False, "error": "unknown tool"}
        fco = {
            "type": "function_call_output",
            "call_id": fc.get("call_id", fc.get("id")),
            "output": json.dumps(tool_result),
        }
        fco_items.append(fco)

    # Compose request2: reproduce prefix and provide fco
    input2 = [{"role": "user", "content": prompt1}]
    input2.extend(reasoning_items)
    input2.extend(assistant_msgs)
    input2.extend(func_calls)
    input2.extend(fco_items)
    input2.append({"role": "user", "content": prompt2})

    print("\n--- TOOLS DEMO: Request 2 (stateless: prefix + tool outputs + prompt2) ---")
    r2 = client.responses.create(
        model=MODEL, input=input2, tools=TOOLS, tool_choice="required", reasoning={"effort": "high"}
    )
    out2 = r2.output or []
    print("Response 2 id:", r2.id)
    for it in out2:
        d = as_dict(it)
        print(" -", d.get("type") or type(it).__name__)
        print(json.dumps(d, indent=2, ensure_ascii=False))


# ---------- CLI ----------


def main() -> None:
    if len(sys.argv) < 2:
        mode = "both"
    else:
        mode = sys.argv[1]
    if mode in ("text", "both"):
        run_text_demo()
    if mode in ("tools", "both"):
        run_tools_demo()


if __name__ == "__main__":
    main()
