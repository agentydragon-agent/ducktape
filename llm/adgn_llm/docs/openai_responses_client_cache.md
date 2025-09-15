# CLI-only OpenAI Responses client with deterministic cache & disk store

Last updated: 2025-09-10T12:00:00Z (sha=01156423)

## Changelog & Decision History
- 2025-09-10 (sha=01156423) — Init: design for a minimal CLI-only Responses client that provides deterministic caching (model+message-sequence key), disk-backed request/response store, and a small, testable API. Decision: implement a small wrapper using a content-addressed key (SHA256 of model + canonical JSON messages) with SQLite index plus per-request JSON blobs on disk. Rationale: simplest auditability, easy testing, no heavy third-party runtime dependency.

## Context & Problem
We want a minimal OpenAI Responses API client usable by our CLIs that provides two additional guarantees:

- Deterministic caching: if the same request (same model and same full input message sequence) is made again, return the cached response instead of calling the network.
- Audit/store: store every request and response on disk for replay, debugging, and offline analysis.

Constraints/requirements from the team:
- Only CLI entrypoints create OpenAI client instances. Library code (non-CLI) must accept a client/adapter and must not instantiate network clients itself.
- Support only what is required for the Responses API (no need to support other SDK APIs now).

Non-goals: streaming support, multi-region distributed cache, complex TTL eviction policies in first iteration, language bindings beyond Python.

## Goals
- Provide a tiny, well-documented wrapper that CLIs instantiate and pass into existing runners (e.g., MiniCodex.create, run_prompt_async). 
- Deterministic keying by model + canonicalized full input (messages sequence) so identical logical requests map to the same cache key.
- Fast local lookup (SQLite index) and durable request/response blobs on disk (JSON) for audit.
- Concurrency-safe (support multiple CLI processes reading/writing the DB) for local workflows.

## Assumptions
- CLI processes run on Linux/macOS; single-node local cache is sufficient.
- We use Python AsyncOpenAI for network calls.
- Cache & store live under `$XDG_CACHE_HOME/adgn-llm/openai-cache` (fallback to `~/.cache/adgn-llm/openai-cache`).

## Requirements
### Functional
- `ResponsesCacheClient` (async) with method `responses_create(model: str, input: list[dict], **kwargs) -> response_obj` that:
  - computes key = SHA256(model + canonical_json(input) + canonical_json(kwargs that affect Response semantics, e.g., instructions, tools list, reasoning params))
  - if key exists in index, return cached response object (parsed back to the same SDK/shape or raw JSON depending on API surface)
  - otherwise call `AsyncOpenAI().responses.create(...)`, store request+response, index key → response_ref, and return response
- All requests & responses stored on disk in human-readable JSON files organized by key or timestamp, and indexed via lightweight SQLite DB that stores: key, model, timestamp, path_to_blob, meta (e.g., truncated excerpt), and optional tags.
- Provide a CLI-friendly factory function that CLIs call to create the client and pass it into application code.

### Non-functional
- Durable: data must survive restarts.
- Reasonable concurrency: support multiple processes but not a distributed lock service.
- Small deps: prefer stdlib + `sqlite3` + `aiosqlite` + optionally `python-dotenv` or `SQLite-only (diskcache removed)` later.

### Versions & Environment
- Target Python 3.11+
- OpenAI Python SDK: used AsyncOpenAI (current repo already imports it)
- Optional deps (iteration 1): `aiosqlite` for async sqlite access, `orjson` or stdlib `json` for canonicalization; fallback to builtin json.

## Prior Art & References
- GPTCache — https://github.com/zilliztech/GPTCache — feature-rich LLM cache (hashes model+prompt and supports multiple backends).
- python-SQLite-only (diskcache removed) — https://github.com/grantjenks/python-SQLite-only (diskcache removed) — disk-backed dict-like cache, multiprocess-safe.
- VCR.py — https://github.com/kevin1024/vcrpy and requests-cache — HTTP-level cassette/record/replay.

## Options Considered

### Option A — Use GPTCache (turnkey)
- Pros:
  - Mature, built for LLM caching; supports multiple backends and integrations.
  - Already provides model+prompt hashing and disk stores.
- Cons:
  - Larger dependency surface; integrates at a higher abstraction level (LangChain/LlamaIndex-focused).
  - We must validate semantic mapping to Responses API (tools, reasoning params) before trusting it.
- When good: if we want a feature-rich cache quickly and are okay with dependency.

### Option B — Use python-SQLite-only (diskcache removed) as a simple persistent memoizer
- Pros:
  - Very small, robust dependency; works as a drop-in memoizer
  - Multiprocess-safe; simple API
- Cons:
  - Only KV store; we still must implement canonical key derivation and separate request/response blob storage (or store both in the value)
  - Not specialized to LLM semantics (we must include all relevant kwargs into key)

### Option C — HTTP-level recording (VCR.py / requests-cache)
- Pros:
  - Works transparently without modifying code that calls the HTTP client
  - Can record full HTTP request/response for general replay
- Cons:
  - We use the official OpenAI SDK which may not run over `requests` in a way that VCR can intercept reliably (SDK internals vary)
  - Not semantically aware of Responses API arguments (tool_choice, instructions) unless we canonicalize the HTTP body mapping

### Option D — DIY SQLite + per-key JSON blobs (recommended)
- Pros:
  - Small, explicit, auditable; we control canonicalization rules and storage layout
  - Easy to reason about deterministic key derivation and to add debugging/trace data
  - Minimal deps (aiosqlite optional)
- Cons:
  - We implement more plumbing ourselves (locking, compaction, TTL if desired)

## Tradeoffs
- GPTCache reduces implementation work but increases dependency surface and requires validation for our exact Responses usage (tools, reasoning kwargs). DIY is simpler to reason about and easier to audit (we own the format).
- Diskcache is minimal and fast; pairing SQLite-only (diskcache removed) with per-request JSON files is a lightweight compromise for iteration speed.

## Decision
Choose Option D (DIY SQLite index + per-request JSON blobs) for the first iteration. Rationale: we want a small, auditable, and explicit cache/store that exactly matches our deterministic-key rule (model + canonical messages + relevant kwargs). This keeps dependencies minimal and aligns with the repository’s preference for clear, auditable behavior. We can wrap/replace with GPTCache later if required.

## Implementation Plan

1) Add a new module: `src/adgn_llm/openai_responses_cache.py` (owner: whoever implements; small API). Objective: provide an async wrapper around `openai.AsyncOpenAI.responses.create` with caching + storage.
   - API shape (suggested):
     ```py
     class ResponsesCacheClient:
         def __init__(self, *, cache_dir: Path | str = None, db_path: Path | str = None, read_only: bool = False):
             ...

         async def responses_create(self, *, model: str, input: list[dict], **kwargs) -> dict:
             """Return response (SDK object or parsed dict)."""
     ```
   - Implementation details:
     - `cache_dir` default: `$XDG_CACHE_HOME/adgn-llm/openai-cache` or `~/.cache/adgn-llm/openai-cache`
     - `db_path` default: `cache_dir/index.sqlite3`
     - Per-request blob path: `cache_dir/blobs/<key>.json` where key = hex(SHA256(...))
     - SQLite table `responses` with columns: key TEXT PRIMARY KEY, model TEXT, created_ts INTEGER, blob_path TEXT, excerpt TEXT, size INTEGER
     - Concurrency: use `PRAGMA journal_mode=WAL` and `aiosqlite` for async access; fall back to `sqlite3` for sync helper functions
     - Key derivation function: `key = sha256(model + '\n' + canonical_json(input) + '\n' + canonical_json({k: kwargs[k] for k in KEYED_KWARGS}))` where `KEYED_KWARGS` are known params that affect output (e.g., `instructions`, `tool_choice`, `tools`, `reasoning`). Canonical JSON uses separators=(',',':'), ensure_ascii=False, sort_keys=True.
     - Stored blob: JSON object `{ "request": {"model":..., "input":..., "kwargs":...}, "response": <raw sdk response model_dump or response.model_dump(exclude_none=True) or response.json>, "meta": {...} }`
     - On cache hit: read blob, construct minimal response-like object or return the stored JSON (the library code should accept either). For type-safety, return the stored JSON dict and document differences vs SDK objects.

2) Provide a small CLI factory helper in `src/adgn_llm/cli_factory.py` that CLIs call (single point of creation):
   - `def build_responses_client_for_cli(cache_dir=None) -> ResponsesCacheClient` which instantiates AsyncOpenAI client internally and wires to the ResponsesCacheClient (or returns a ResponsesCacheClient that holds an inner `openai_client` instance). Important: only CLI code will call this factory.

3) Update CLI entrypoints (adgn-properties CLI in `src/adgn_llm/properties/cli.py`, mini_codex CLI) to call the factory once near startup and pass `client` into all library functions (we already began enforcing that pattern in agent_runner.run_prompt_async). Replace ephemeral `AsyncOpenAI()` calls with the injected client in CLIs.

4) Tests & examples
   - Unit tests under `tests/` for:
     - `test_key_determinism`: same model+messages+kwargs → same key
     - `test_cache_hit`: first call stores, second call returns without issuing network call (use a mocked AsyncOpenAI client)
     - `test_store_blob`: ensure blob file written and contains expected fields
     - `test_concurrency`: spawn two concurrent requests for same key and ensure single network call executed (lock via SQLite row/PRAGMA or an asyncio.Lock per key in-process; for inter-process, rely on WAL and `INSERT OR IGNORE` semantics)
   - Integration test: a small recorded-response test using a fake AsyncOpenAI that returns a deterministic response and assert cached retrieval.

5) Documentation
   - Update docs: `docs/openai_responses_client_cache.md` (this file), and add usage snippet in `CLAUDE.md` / CLI README.

## Sequencing & Rollout
- Phase 1 (Dev, fast): Implement module + unit tests + local README (no changes to production CLIs). Verify via unit tests.
- Phase 2 (CLIs): Update CLI entrypoints to create the client via factory and pass into runners. Run local smoke tests (dry-run mode).
- Phase 3 (Integration): Add integration tests (mock network or use probe mode) and run pre-commit/CI.
- Phase 4 (Optional): Replace DIY store with GPTCache/SQLite-only (diskcache removed)-based backend if feature needs grow.

## Reversibility
- All changes are additive; we can revert CLI wiring to create raw AsyncOpenAI clients if needed.
- Cache and blob files are separate under `cache_dir`; removal is a single `rm -rf` operation. DB schema changes should be done via migrations (or non-invasive columns first).

## Test Plan & Acceptance Criteria
- Unit tests (run via `uv run pytest -q`): key derivation, blob write, cache hit vs miss, concurrency-locking unit tests.
- Integration: run `adgn-properties` with `--dry-run` and verify cache saved under `$XDG_CACHE_HOME/adgn-llm/openai-cache`.
- Acceptance: repeated identical calls must return cached JSON without performing network call (mocked verification). All requests are stored as `/openai-cache/blobs/<key>.json`.

## Risks & Mitigations
- Risk: forgetting to include a relevant kwarg into the key (e.g., `instructions`, `tools`) leading to incorrect cache hits. Mitigation: define `KEYED_KWARGS` explicitly and include tests that exercise tool-calls/instructions and ensure they affect keys.
- Risk: DB locking/contention under heavy parallel runs. Mitigation: WAL mode, `INSERT OR IGNORE` semantics, lightweight filesystem locks (flock) or process-local in-memory locks for single-process concurrency.
- Risk: SDK response object shapes differ across versions. Mitigation: store raw JSON `response.model_dump(exclude_none=True)` and return JSON dict to callers; keep conversion helpers in client for optional backward compatibility.

## Open Questions (with owners/next pointers)
- Q: Which kwargs must be considered part of the request key exactly? (e.g., `instructions`, `tools`, `tool_choice`, `reasoning`, `store`) — Owner: implementer — Next: produce canonical `KEYED_KWARGS` list and add tests.
- Q: Should we return SDK response objects on cache hit or JSON dicts? Owner: API owner — Next: default to JSON dicts (easier/safer) and provide a small compatibility wrapper if SDK objects are required.

---

## Example usage (CLI factory + call)

```python
# CLI main (only CLI creates the client)
from adgn_llm.openai_responses_cache import build_responses_cli_client

async def main():
    client = build_responses_cli_client(cache_dir=None)  # constructs AsyncOpenAI internally
    # pass `client` into library code that expects an AsyncOpenAI-like object
    await run_prompt_async(prompt, model, specs, client=client)
```

## Implementation notes (developer reminders)
- Canonical JSON must be byte-for-byte stable: use `json.dumps(obj, separators=(",",":"), ensure_ascii=False, sort_keys=True)`.
- Key = hex(sha256(bytes(model, 'utf-8') + b"\n" + canonical_bytes_of_input + b"\n" + canonical_bytes_of_keyed_kwargs)).
- Blob storage layout: `<cache_dir>/blobs/<first2hex>/<key>.json` (spread into 256 buckets by hex prefix to avoid large single-directory lists).
- Provide a small `gc` utility to remove old blobs if desired later.


## Persistence options (proposal)

We should persist the cache in a durable, queryable store so operators can inspect, query, and export cached requests/responses. Options (short pros/cons):

- Option P1 — Keep SQLite-only (diskcache removed) (current) and add DB export/migration
  - Pros: minimal effort, SQLite-only (diskcache removed) is multiprocess-safe and fast; keeps existing proxy behavior.
  - Cons: not an RDBMS; querying requires either opening SQLite-only (diskcache removed) programmatically or exporting to a DB. Good interim choice.

- Option P2 — SQLite (recommended first-step persistent store)
  - Pros: single-file, zero-ops, queryable with sqlite3/aiosqlite, supports WAL for concurrency; easy to inspect and backup; fits offline workflows.
  - Cons: not ideal for heavy concurrent writes at extreme scale (but fine for CLI/local workloads).
  - Implementation: store a canonical record per key (key, model, input_json, kwargs_json, ndjson_frames OR response_json, created_ts). Provide async helper module `responses_db.py` with a small migration/import tool to copy existing SQLite-only (diskcache removed) entries into the DB.

- Option P3 — Postgres (production / multi-user)
  - Pros: robust, networked, good for long-lived shared caches, allows efficient querying and aggregation.
  - Cons: operational overhead, requires credentials and network access; heavier than necessary for single-host use.

- Option P4 — Vector DB + metadata (for semantic queries later)
  - Pros: if/when we add semantic features, index embeddings + metadata to query similar prompts.
  - Cons: out of scope for exact-key caching; heavier infra.

Recommendation: start with Option P2 (SQLite) as the canonical persisted backend for the first iteration. Keep SQLite-only (diskcache removed) as a warm in-memory/fast lookup layer if needed, and provide a small `import_from_SQLite-only (diskcache removed)()` path to populate the DB.

## Proxy name — short suggestions

We should use a short, memorable service/module name for local use and docs. Options:

- `rspcache` — short for "responses cache" (good balance of brevity + meaning)
- `resp-proxy` — explicit: responses proxy
- `responses-proxy` — explicit, slightly longer
- `rspdb` — short, hints at DB-backed store (if/when we make DB default)

Recommendation: `rspcache` for the package/module and CLI service name (e.g., `uvicorn adgn_llm.rspcache:app` or `rspcache --port 8000`). If/when we make DB-backend the default, `rspdb` could be a separate module handling persistence.

## Single-DB design options (detailed)

You requested a single-database design (no separate cache + DB). Below are practical options for that design, with tradeoffs and concrete schema/flow suggestions so we can pick an authoritative approach.

Option S1 — SQLite single-table (simplest)
- Schema (single table `responses`):
  - `key TEXT PRIMARY KEY` — deterministic request key
  - `model TEXT`
  - `input_json TEXT`
  - `kwargs_json TEXT`
  - `response_json TEXT`
  - `created_ts INTEGER`
  - `status TEXT` (optional: `complete` / `in_progress`)
- Pros: minimal complexity; everything in one row; easy to implement and query with SQL; zero extra infra.
- Cons: if responses are large (many MB) the single JSON column can get big; whole-row reads/writes may be heavier than small cache gets; streaming writes need to reload and rewrite the full JSON unless you use `status` and incremental frames (see S2).
- When to pick: very low-to-moderate QPS, single-host use, small responses; want absolute simplicity.

Option S2 — SQLite with frames table (recommended for streaming and large responses)
- Schema: two tables
  - `responses` (key PK, model, input_json, kwargs_json, created_ts, status)
  - `response_frames` (id INTEGER PK, key TEXT, seq INTEGER, frame_json TEXT) — frames ordered by seq
  - Index: `idx_response_frames_key_seq` on (key, seq)
- Behavior for streaming: create `responses` row with status=`in_progress`; INSERT frames as they arrive with incremental `seq`; on stream completion set status=`complete` and optionally compute a small summary JSON in `responses.response_json` for fast single-row reads.
- Pros: scalable for large/NDJSON streams; avoids rewriting huge blobs; can stream-read frames back to clients efficiently.
- Cons: slightly more schema and read-path complexity; need transactions to guarantee consistency for short races.
- When to pick: you expect streaming NDJSON / large responses or want efficient append without rewriting big JSON blobs.

Option S3 — Postgres JSONB single-table (production scale)
- Schema similar to S1 or S2 but using Postgres with `jsonb` for `response_json` and `response_frames` as a separate table if desired.
- Pros: scales well, supports advisory locks for de-duplication, richer query indices (GIN on jsonb), higher concurrency.
- Cons: operational overhead (run Postgres), not zero-install local dev convenience.
- When to pick: shared multi-user deployment, higher QPS, or need robust analytical queries.

Concurrency / deduplication pattern (single DB)
- Goal: avoid duplicate upstream calls for the same key launched concurrently by multiple processes.
- Use DB-native upsert/transaction pattern:
  1. Attempt to INSERT a `responses` row with status=`in_progress` using `INSERT OR IGNORE` (SQLite) or `INSERT ... ON CONFLICT DO NOTHING` (Postgres). If inserted: this process is the writer and proceeds to call upstream and populate frames/response.
  2. If INSERT failed (row exists), SELECT the row. If `status='complete'` return stored response. If `status='in_progress'` then wait / poll (or use lightweight advisory locks in Postgres) until complete; then read and return. Use a short timeout.
- Streaming: writer inserts frames incrementally. Readers that detect `in_progress` can either (a) wait and stream frames as they accumulate (if you want live tail), or (b) wait until completion and then read frames.

Atomicity & transactions
- Use short transactions and WAL in SQLite (PRAGMA journal_mode=WAL). Keep writer transactions small (do not hold locks while calling upstream). Use the INSERT-as-lock pattern to claim the write responsibility.

Schema examples (SQLite S2)

CREATE TABLE responses (
  key TEXT PRIMARY KEY,
  model TEXT,
  input_json TEXT,
  kwargs_json TEXT,
  response_summary_json TEXT,
  status TEXT NOT NULL DEFAULT 'in_progress',
  created_ts INTEGER
);

CREATE TABLE response_frames (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT NOT NULL,
  seq INTEGER NOT NULL,
  frame_json TEXT NOT NULL
);
CREATE INDEX idx_response_frames_key_seq ON response_frames(key, seq);

Streaming write flow (S2)
- Writer process:
  - Try INSERT INTO responses(key, model, input_json, kwargs_json, status, created_ts) VALUES(..., 'in_progress', now) ON CONFLICT(key) DO NOTHING.
  - If inserted -> caller proceeds to call upstream stream, parse frames, INSERT INTO response_frames(key, seq, frame_json) for each parsed frame, and at the end UPDATE responses SET status='complete', response_summary_json=... WHERE key=?.
  - If not inserted -> someone else is writing: poll responses.status until 'complete' or timeout; then read frames.

Read flow (S2)
- SELECT status FROM responses WHERE key=?; if missing -> miss; if complete -> read frames via SELECT frame_json FROM response_frames WHERE key=? ORDER BY seq;

Advantages of single-DB S2 vs dual (DB+SQLite-only (diskcache removed))
- Simpler operations: just one store to manage and backup.
- Queryability: frames and metadata reside in DB; no need to sync cache → DB.
- Avoids duplication and storage overhead.

Tradeoffs
- Read latency for hot keys may be higher than an optimized SQLite-only (diskcache removed) get (but SQLite with proper indexes + PRAGMA and a prepared connection pool is fast; often ~sub-ms to low-ms on SSD for single-row reads).
- If you need extreme low-latency hot-path (<1ms), you may still want an in-process memory cache, but that is optional.

Administration & maintenance
- Backups: copy SQLite file (use sqlite .backup for safety). Consider periodic VACUUM to reclaim space.
- Retention: implement retention policy via DELETE WHERE created_ts < cutoff or MOVE old rows to archive DB.
- Migration: provide `import_from_SQLite-only (diskcache removed)()` helper if migrating from prior SQLite-only (diskcache removed)-only store.

Recommendation (single DB):
- Use SQLite S2 (responses + response_frames) as the default single-database design. It handles streaming NDJSON efficiently, provides queryability, and is zero-op for dev. Use the INSERT-as-lock pattern to avoid duplicate upstream calls. Keep response_summary_json in the responses table for quick single-row reads.

Next step I can implement now (one):
- Wire the existing proxy to use S2 SQLite flow (insert-or-ignore claim, stream frames into response_frames, update status/summary on complete). I can implement the DB module and integrate it into the proxy in a single change.

Which single-step do you want me to take next? Implement S2 SQLite wiring into the proxy now, or produce the exact SQL and pseudocode for your review?  
