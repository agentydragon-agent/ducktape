# Sample eval rollout — claude-haiku-4-5 against Grocy MCP

One-shot rollout of `//x/grocy_mcp/eval:cli --api=anthropic` against a
freshly-booted Grocy container. Captured 2026-04-18.

## Files

| File                                          | What it is                                                                   |
| --------------------------------------------- | ---------------------------------------------------------------------------- |
| `grocy_eval_20260418_013052_summary.json`     | `EvalResult`: model, postmortem text, transcript path                        |
| `grocy_eval_20260418_013052_transcript.jsonl` | Intended to be one JSONL Message per line (**empty — see "Transcript bug"**) |
| `run.log`                                     | Full stdout/stderr of the CLI run, including every MCP tool call             |
| `grocy_data/`                                 | Bind-mount target for `/config/data` (**empty — see "DB capture"**)          |

## How it was run

```bash
source /root/.claude/session-env/<session>/sessionstart-hook-0.sh
TESTCONTAINERS_RYUK_DISABLED=true \
GROCY_MCP_HOST_NETWORK=1 \
ANTHROPIC_API_KEY=… \
  bb --bazelrc=$SESSION_BAZELRC run --remote_executor= //x/grocy_mcp/eval:cli \
    -- --api=anthropic --output-dir=<this dir>
```

- `GROCY_MCP_HOST_NETWORK=1` — required in the gvisor sandbox (IPv4
  forwarding off, so Docker port publishing is a no-op). Ships as a
  real toggle in `grocy_container.py` alongside this rollout.
- `TESTCONTAINERS_RYUK_DISABLED=true` — same reason; the reaper needs
  port publishing to discover its own socket.

## Known limitations of this run

1. **Anthropic rejects four auto-generated tools.** Grocy's OpenAPI
   declares a shared query parameter literally named `query[]` (PHP
   array style). FastMCP faithfully surfaces that as a JSON-schema
   property key with brackets, which Anthropic's Messages API rejects
   (`properties` keys must match `^[a-zA-Z0-9_.-]{1,64}$`). This run
   worked around it by temporarily disabling the four affected tools
   (`list_users`, `list_product_locations`, `list_product_stock_entries`,
   `list_location_stock`) in the local `tool_metadata.py` —
   **not committed**; the tool surface on devel is unchanged. A proper
   fix would rewrite `query[]` at the MCP-tool boundary (either in
   `fix_openapi_spec.py` or in `server._customize_component`).

2. **Transcript is empty.** `run.py` pulls messages from
   `session.state["messages"]` after the agent completes, which assumes
   `agent_framework` auto-attaches `InMemoryHistoryProvider` when an
   `AgentSession` is passed with no explicit providers. Evidently the
   auto-attach didn't fire in this run. The postmortem text lives in
   the summary JSON instead — the transcript itself needs a followup
   to either explicitly wire the provider or fall back to collecting
   `AgentRunResponse.messages` per run.

3. **`grocy_data/` is empty.** The bind mount at `/config/data`
   worked, but Grocy had only just finished initialising when the
   eval's first batch call hit it; config.php wasn't yet visible to
   the caller, most tool calls returned empty 200s, and Grocy never
   got far enough to actually write `grocy.db`. `wait_for_grocy_ready`
   should probably wait for a heavier endpoint (e.g. a successful
   `list_entities('products')`) before yielding.

## What the agent found

The postmortem (see `summary.json`) is the actual signal. Haiku flags:

- The generic `create_entities` vs the typed `create_product` split is
  confusing — locations and quantity units only have the generic
  tool, products have a dedicated one.
- Tool errors bubble up as raw `JSONDecodeError` tracebacks instead
  of actionable messages, so when Grocy returned empty it took the
  agent several failed calls + a `get_system_info` probe to figure
  out the cause.
- Parameter interdependencies aren't documented (e.g. the acceptable
  units for `qu` in `add_stock` are determined by the product's
  stock QU — the description doesn't say so).
- No way to discover available quantity-unit conversions.
- Several entity-type enums have near-duplicate names (`shopping_list`
  vs `shopping_lists`, `product_barcodes` vs `product_barcodes_view`,
  `recipes_pos` vs `recipes_pos_resolved`) with no guidance on
  which to pick.
