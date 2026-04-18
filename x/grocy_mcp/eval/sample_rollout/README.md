# Sample eval rollout — claude-haiku-4-5 against Grocy MCP

One real run of `//x/grocy_mcp/eval:cli --api=anthropic` (model
`claude-haiku-4-5-20251001`) against a freshly-booted Grocy container.
Captured on `2026-04-18` after the eval-fix landed in this PR.

## Files

| File                                          | What it is                                                             |
| --------------------------------------------- | ---------------------------------------------------------------------- |
| `grocy_eval_20260418_041517_transcript.jsonl` | Full message-by-message rollout, one JSON Message per line             |
| `grocy_eval_20260418_041517_summary.json`     | `EvalResult`: model, postmortem text, transcript path                  |
| `grocy_data/grocy.db`                         | The Grocy SQLite DB after the agent finished — open to see what landed |

## How it was run

```bash
source /root/.claude/session-env/<session>/sessionstart-hook-0.sh
TESTCONTAINERS_RYUK_DISABLED=true \
GROCY_MCP_HOST_NETWORK=1 \
ANTHROPIC_API_KEY=… \
  bb --bazelrc=$SESSION_BAZELRC run --remote_executor= //x/grocy_mcp/eval:cli \
    -- --api=anthropic --output-dir=<this dir>
```

## Did Haiku do the operations correctly?

Yes — 5/5 stock entries match the natural-language prompt, including
sensible interpretations of the loose dates ("good through June 2026"
→ `2026-06-30`, "mid-2027" → `2027-06-15`):

| Product     | Location | Stock QU | Amount | Best before  | Prompt said                                      |
| ----------- | -------- | -------- | -----: | ------------ | ------------------------------------------------ |
| Rice        | Pantry   | Bag      |      2 | `2026-06-30` | "2 bags of rice that are good through June 2026" |
| Olive Oil   | Pantry   | Liter    |      1 | `2027-06-15` | "a liter of olive oil that keeps until mid-2027" |
| Milk        | Fridge   | Liter    |      3 | `2026-05-01` | "3 liters of milk expiring 2026-05-01"           |
| Eggs        | Fridge   | Piece    |     12 | `2026-05-15` | "a dozen eggs expiring 2026-05-15"               |
| Frozen Peas | Freezer  | Bag      |      1 | `2027-01-01` | "a bag of frozen peas, best before 2027-01-01"   |

Open `grocy_data/grocy.db` in any SQLite tool to verify directly.

The fresh Grocy install only ships with `Fridge` (location) and
`Piece` / `Pack` (units); Haiku discovered that with `list_locations`
and `list_quantity_units`, then created `Pantry`, `Freezer`, `Liter`,
`Bag` (and `Kilogram`, unused but harmless) before touching products.
The products themselves went through the typed `create_product` tool;
stock was added in a single batched `add_stock` call.

## What the agent flagged in its postmortem

(Full text in `summary.json`.) The interesting friction Haiku hit:

- `create_entities` (generic) vs `create_product` (typed) is confusing
  — locations and quantity units only have the generic, products have
  the typed, and the docs don't explain when to use which.
- The MCP server returned empty 200s on a few tool calls early on
  (these eventually resolved as Grocy finished initializing); the
  errors surfaced as raw Python `JSONDecodeError` tracebacks rather
  than actionable messages.
- `add_stock` requires `qu` and `location` per item with "no defaults"
  but doesn't explain what determines the acceptable units (it's the
  product's stock QU).
- No tool to discover available quantity-unit conversions.
- Several entity-type enums have near-duplicate names with no
  guidance: `shopping_list` vs `shopping_lists`, `product_barcodes`
  vs `product_barcodes_view`, `recipes_pos` vs `recipes_pos_resolved`.
