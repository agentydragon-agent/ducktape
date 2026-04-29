"""Resurrect a finished rollout's transcript and ask the model a follow-up.

A rollout's `transcript_*.jsonl` is a verbatim record of every Message AF
saw — including the cryptographic state that lets the same provider
continue the conversation (Anthropic thinking signatures land in
`Content.protected_data`; OpenAI Responses reasoning IDs ride along the
same way, both round-tripped by `SerializationMixin`). That's enough to
re-open the conversation post-mortem and ask the model *why* it did
something, without re-creating the sandbox container or replaying any
tool side-effects.

Usage:

    bazelisk run //skills/eval_infra:resurrect -- \\
      --transcript /path/to/transcript_skill_on.jsonl \\
      --question "Why did you start calling exec({}) with no arguments?" \\
      --output /path/to/transcript_skill_on.followup.jsonl

The output JSONL is the input transcript verbatim, plus the appended
user question and the assistant's reply. `tool_choice="none"` is sent so
the model produces a textual answer instead of fresh tool calls; the
historical tool definitions are not needed because no new tool use is
permitted.

Unsupported on purpose: container resurrection, multi-turn back-and-forth,
streaming. Add those when there's a reason to.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from agent_framework import Message

from skills.eval_infra.af_chat_client import build_model_client

logger = logging.getLogger(__name__)


def _load_transcript(path: Path) -> list[Message]:
    return [Message.from_json(line) for line in path.read_text().splitlines() if line.strip()]


def _write_transcript(path: Path, messages: list[Message]) -> None:
    path.write_text("\n".join(m.to_json() for m in messages) + "\n")


async def _async_main(args: argparse.Namespace) -> None:
    messages = _load_transcript(args.transcript)
    logger.info("Loaded %d messages from %s", len(messages), args.transcript)

    messages.append(Message("user", [args.question]))

    client = build_model_client(api=args.api, model=args.model)
    # `tool_choice="none"` forbids the model from emitting fresh tool calls,
    # so we don't need to re-supply the historical tool schemas.
    response = await client.get_response(messages, options={"tool_choice": "none"})

    answer_messages = list(response.messages)
    logger.info("Model returned %d message(s)", len(answer_messages))

    answer_text = "\n".join(c.text for msg in answer_messages for c in msg.contents if c.type == "text" and c.text)
    print(answer_text or "<no text response>")

    extended = messages + answer_messages
    _write_transcript(args.output, extended)
    logger.info("Wrote extended transcript (%d messages) to %s", len(extended), args.output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True, help="Existing transcript JSONL.")
    parser.add_argument("--question", required=True, help="Follow-up question to append as a user message.")
    parser.add_argument("--output", type=Path, required=True, help="Where to write the extended transcript.")
    parser.add_argument("--api", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    if args.api == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; refusing to run.")
    if args.api == "openai" and not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set; refusing to run.")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
