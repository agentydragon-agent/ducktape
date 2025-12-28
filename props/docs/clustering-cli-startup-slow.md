## Clustering CLI startup latency investigation (Dec 2025)

### Symptoms
- `tests/props/clustering/test_e2e.py::test_clustering_http_mode_assign_to_cluster` was taking ~27–30 s and sometimes timing out at 30 s. Each docker exec (create-cluster, assign-to-cluster) logged ~5–6 s elapsed even though the CLI reported `elapsed≈0.2s` inside the command.
- Per-chunk exec logs showed a ~4.8–5.0 s delay before the first stdout byte on every exec; after that, the stream closed in <1 s.

### Findings
- The delay is not Docker/streaming. A standalone `aiodocker exec python -c "print('hi')"` returns in ~0.05 s.
- The cost is Python startup/import in the clustering CLI: each exec pays ~6 s before it prints.
- Import-time profiling inside the container:
  - `python -X importtime -m clustering_util.cli --help` ≈ 6.4 s wall.
  - `import helpers` shows **`rfc3987_syntax.syntax_helpers`** alone taking ~3.4 s self-time. It loads a Lark grammar and constructs many Earley parsers at import time.
  - SQLAlchemy/OpenAI/MCP/Pydantic/Alembic add ~1 s combined; the dominant cost is `rfc3987_syntax`.
- Minimal repro outside props:
  - `from jsonschema import FormatChecker; FormatChecker()` triggers `rfc3987_syntax` and costs ~0.66 s self-time even outside Docker. In the container this scales to ~3 s.
  - That package is pulled in via jsonschema’s format extras (IRI/URI validators), which are brought in through our pydantic/OpenAI/jsonschema stack when the CLI imports props helpers/DB.

### Root cause
- Importing jsonschema’s format checker → imports `rfc3987_syntax` → builds multiple Lark parsers at module import. Every CLI exec spawns a fresh interpreter and redoes this work.

### Next steps (possible mitigations)
1. Avoid per-exec interpreter startup for these steps (e.g., batch the two assign calls, or expose a resident helper/Tool in MCP instead of spawning three processes).
2. Make the clustering CLI “lightweight”:
   - Defer heavy imports (jsonschema/OpenAI/MCP) until inside command bodies, or use a slim DB helper that doesn’t import the format checker path.
   - Optionally disable jsonschema format loading for this path if not needed.
3. If we keep the CLI, consider replacing `rfc3987_syntax` with a cheaper validator or stub in test mode.

### Current instrumentation cleanup
- Removed the temporary high-volume exec-stream and per-phase timing logs added during investigation; they were useful for debugging but too noisy to keep enabled by default.

