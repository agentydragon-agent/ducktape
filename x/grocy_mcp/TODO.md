## Fold `server_instructions.md` conventions into tool descriptions

claude.ai does not expose MCP `initialize.instructions` to the LLM
(verified 2026-04-19). The eval harness compensates by prepending the
markdown to the system prompt manually; claude.ai has no equivalent
injection point.

Make tool descriptions more self-contained so they work well without
server-level instructions. Key conventions that currently live only in
`server_instructions.md` (e.g. `amount_opened` semantics, when to use
`stock_set` vs `stock_add`, unit handling) should be folded into the
relevant tool descriptions themselves.

## Finish the `<entity>_<verb>` rename

The first pass renamed the CRUD / stock / shopping-list families. The
remainder needs a bit more care:

- **Stock views** — `get_expiring_stock`, `get_below_minimum_stock`,
  `get_expired_stock`, `list_volatile_stock`. `stock_expiring_list` etc.
  works mechanically but "stock views keyed on a query" doesn't feel like
  a true entity; a separate "queries" namespace
  (`stock_query_expiring` / `stock_query_expired` / …) or grouping under
  `volatile_stock_*` might read better. Decide before renaming.
- **Singletons** — `get_system_info`, `get_db_changed_time`,
  `get_current_user`. These are zero-argument reads on singleton
  resources; dropping the verb (`system_info`, `db_changed_time`,
  `current_user`) reads more naturally as MCP resources than as tools.
- **Product stock helpers** (OpenAPI) — `get_product_stock`,
  `open_product_stock`, `transfer_product_stock` (already disabled). The
  `<entity>_<verb>` rename is mechanical (`product_stock_get`,
  `product_stock_open`) but the `product_stock` name implies it's a
  standalone entity, which it isn't — it's a derived view over
  `stock_entries` filtered by product. Worth thinking about whether to
  promote to a batch tool that groups with `stock_*`.

## Consider per-test container isolation for e2e tests

Tests currently share a session-scoped Grocy container and use uuid
suffixes to avoid name collisions. Container startup is ~25-30s
(LinuxServer image runs s6-overlay + nginx + PHP + SQLite migrations),
so function-scoped containers would make the suite too slow (~4-5 min
for 9 tests).

Options to explore:

- Lighter Grocy container image (skip nginx/s6, run PHP built-in server
  directly against a fresh SQLite DB).
- Grocy's built-in demo-mode reset endpoint (if one exists).
- Per-test database reset via direct SQLite file swap.

## Per-turn eval logging

`agent.run()` is a black box — no per-turn callbacks in
agent_framework. Replace with a manual conversation loop (like
`skills/info_gathering/evals/function_learning/function_learning.py`)
to log timestamps, token counts, and tool call names on every LLM
turn. This would let us see which tool calls are slow and where time
is spent during eval runs.

## `shopping_list_clear` checks each DELETE (landed in #1345)

Tombstone — keep until the next design pass so we remember it was an
intentional fix rather than an oversight.
