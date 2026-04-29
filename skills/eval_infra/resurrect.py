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

For Anthropic, the historical prefix is marked with `cache_control:
ephemeral` (5-minute TTL). The first call against a transcript pays the
1.25x cache-write rate; subsequent calls within the TTL pay the 0.1x
cache-read rate. Token accounting is printed to stderr after each call
so the operator can verify caching is in effect.

Unsupported on purpose: container resurrection, multi-turn back-and-forth,
streaming, OpenAI prompt caching (Responses API caches automatically;
Chat Completions doesn't take a marker). Add those when there's a reason.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

from agent_framework import BaseChatClient, Message, UsageDetails
from agent_framework.anthropic import AnthropicClient

from skills.eval_infra.af_chat_client import build_model_client

logger = logging.getLogger(__name__)


def _load_transcript(path: Path) -> list[Message]:
    return [Message.from_json(line) for line in path.read_text().splitlines() if line.strip()]


class _PrefixCachingAnthropicClient(AnthropicClient):
    """AnthropicClient that marks the last historical message for prompt caching.

    AF doesn't expose Anthropic's ``cache_control`` markers through ``ChatOptions``,
    so a long-history follow-up call ships the entire transcript as fresh input
    every time. We override ``_prepare_messages_for_anthropic`` to attach
    ``cache_control: {"type": "ephemeral"}`` to the last content block of the
    last *historical* message. Anthropic caches everything up to and including
    that block, so the second resurrect call within the cache TTL (5 min default)
    pays only for the new user question + reply.

    Assumes the caller appended exactly one new user message at the end.
    """

    def _prepare_messages_for_anthropic(self, messages: Any) -> list[dict[str, Any]]:
        prepared = super()._prepare_messages_for_anthropic(messages)
        # Walk back from the second-to-last message (skip the new user question) and
        # mark the last non-empty content block we find. Anthropic caches up through
        # the last cache_control marker, so this caches the full historical prefix.
        for i in range(len(prepared) - 2, -1, -1):
            blocks = prepared[i].get("content")
            if isinstance(blocks, list) and blocks:
                blocks[-1]["cache_control"] = {"type": "ephemeral"}
                logger.info("cache_control set on prepared[%d] (role=%s)", i, prepared[i].get("role"))
                return prepared
        logger.warning("no historical message had a non-empty content list; not marking cache breakpoint")
        return prepared


def _write_transcript(path: Path, messages: list[Message]) -> None:
    path.write_text("\n".join(m.to_json() for m in messages) + "\n")


async def _async_main(args: argparse.Namespace) -> None:
    messages = _load_transcript(args.transcript)
    logger.info("Loaded %d messages from %s", len(messages), args.transcript)

    messages.append(Message("user", [args.question]))

    client: BaseChatClient[Any] = (
        _PrefixCachingAnthropicClient(model=args.model)
        if args.api == "anthropic"
        else build_model_client(api=args.api, model=args.model)
    )
    # `tool_choice="none"` forbids the model from emitting fresh tool calls,
    # so we don't need to re-supply the historical tool schemas.
    response = await client.get_response(messages, options={"tool_choice": "none"})

    answer_messages = list(response.messages)
    logger.info("Model returned %d message(s)", len(answer_messages))

    answer_text = "\n".join(c.text for msg in answer_messages for c in msg.contents if c.type == "text" and c.text)
    print(answer_text or "<no text response>")

    _print_token_accounting(response.usage_details)

    extended = messages + answer_messages
    _write_transcript(args.output, extended)
    logger.info("Wrote extended transcript (%d messages) to %s", len(extended), args.output)


def _get_int(usage: UsageDetails, *keys: str) -> int:
    """Read the first present numeric field from a UsageDetails dict, defaulting to 0."""
    for k in keys:
        v = usage.get(k)
        if isinstance(v, int):
            return v
    return 0


def _print_token_accounting(usage: UsageDetails | None) -> None:
    """Print a one-block token accounting summary to stderr.

    Anthropic and OpenAI report input tokens partitioned by cache disposition:
    ``input_token_count`` is the *uncached* portion only; the cache hits and
    new cache writes are reported in separate provider-namespaced fields
    (``anthropic.cache_read_input_tokens``, ``anthropic.cache_creation_input_tokens``;
    ``openai.cached_input_tokens`` / ``prompt/cached_tokens`` on the OpenAI side).
    Total input = uncached + cache_read + cache_creation.

    Pricing-wise (Anthropic): uncached billed at 1x, cache writes at 1.25x for the
    5-minute TTL, cache reads at 0.1x. So a long-prefix follow-up that lands
    entirely in cache costs ~10% of a non-cached call — which is the whole point.
    """
    if not usage:
        print("\n[token accounting] no usage_details on response", file=sys.stderr)
        return
    uncached = _get_int(usage, "input_token_count")
    out = _get_int(usage, "output_token_count")
    cache_read = _get_int(
        usage, "anthropic.cache_read_input_tokens", "openai.cached_input_tokens", "prompt/cached_tokens"
    )
    cache_create = _get_int(usage, "anthropic.cache_creation_input_tokens")
    total_input = uncached + cache_read + cache_create
    hit_pct = (cache_read / total_input * 100) if total_input else 0.0
    print(
        f"\n[token accounting] total_input={total_input} "
        f"(uncached={uncached}, cache_read={cache_read}, cache_creation={cache_create}, "
        f"hit_rate={hit_pct:.1f}%) output={out}",
        file=sys.stderr,
    )
    if total_input > 1024 and cache_read == 0 and cache_create == 0:
        print(
            "[token accounting] WARNING: prefix caching is not taking effect — "
            "no cache reads and no cache writes. Every call will be billed at full input rate.",
            file=sys.stderr,
        )


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
