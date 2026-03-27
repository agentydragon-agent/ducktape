# Prompt Caching Investigation — Anthropic API + autogen

## Problem

The function learning eval makes ~36 LLM calls per run with a growing conversation
history (1500→10000+ tokens). Prompt caching should save ~70% of input token cost by
caching the conversation prefix. But `cache_read_input_tokens` was always 0.

## Root Causes Found

### 1. Prompt caching requires explicit `cache_control` markers

Caching does **not** happen automatically. The Anthropic API requires explicit
`cache_control: {"type": "ephemeral"}` on content blocks or as a top-level
parameter. Without it, `cache_creation_input_tokens` and `cache_read_input_tokens`
are always 0.

### 2. autogen doesn't pass `cache_control` to the Anthropic API

`AnthropicChatCompletionClient` builds `request_args` by cherry-picking specific
params (`top_p`, `top_k`, `stop_sequences`, `metadata`). `cache_control` is not in
the list and gets silently dropped. Even passing it via `extra_create_args` doesn't
work because it's not in the forwarding whitelist.

**Fix:** Monkey-patch `raw_client.messages.create` to inject `cache_control` on the
system message and the last conversation message.

### 3. Haiku 4.5's minimum cacheable prefix is ~4096 tokens, not 1024

The docs say "model-dependent (typically 1024-2048 tokens)." Empirically tested
with `curl` against the raw API using a personal Anthropic API key:

| System prompt tokens | `cache_creation_input_tokens` |
| -------------------- | ----------------------------- |
| 609                  | 0                             |
| 1209                 | 0                             |
| 3009                 | 0                             |
| 3909                 | 0                             |
| 4209                 | **4202** (caching activated)  |

Haiku 4.5 (`claude-haiku-4-5-20251001`) requires ~4096 tokens before caching
activates. Prefixes shorter than this silently don't cache (no error, just 0 in
the usage fields).

This means our ~1500 token system prompt alone won't cache. But the conversation
prefix (system + tools + prior turns) exceeds 4096 tokens by turn ~5, so caching
the last message block caches the growing prefix for subsequent turns.

### 4. Cache hits confirmed with large enough prefix

```
Call 1: input=9, cache_read=0, cache_create=24002   (wrote to cache)
Call 2: input=9, cache_read=24002, cache_create=0    (cache HIT)
```

## Implementation

`_enable_prompt_caching()` in `function_learning.py` monkey-patches the Anthropic
client to:

1. Convert system message from string to content block with `cache_control`
2. Place `cache_control` on the last message in the conversation

This ensures the conversation prefix is cached once it exceeds the minimum threshold.

## Cost Impact (estimated)

For a 30-turn run on Haiku 4.5:

- **Without caching:** ~600K input tokens @ $1/1M = $0.60/run
- **With caching (turns 5-30):** ~150K uncached + ~450K cached @ $0.10/1M = $0.20/run
- **Savings:** ~67%
