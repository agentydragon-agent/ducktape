# Agentplane shared setup audit

**Observed evidence:** source audit at `1081df24bd`, scoped to shared app/auth/client/test setup.
No runtime behavior was exercised. **Decision:** keep this slice documentation-only; the short
remaining repetitions do not justify a new shared factory or base class.

## Candidates and disposition

- **App composition:** `x/agentplane/app/main.py`, `action_service/main.py`, and
  `llm_ingress/main.py` repeat logging, Kubernetes client construction, and Uvicorn startup.
  Their resource ownership differs: app watches/bridge/store and optional kubeconfig; Action
  Service schema verification/executors/lease tasks and in-cluster auth; ingress streaming HTTP
  timeouts and wire-log suppression. Leave these explicit rather than parameterizing a common
  lifecycle. The app and Action Service also repeat a short Pydantic settings-source hook with
  distinct environment selectors; no new settings abstraction is justified for those two hooks.
- **Authentication:** `sandbox_auth/principal.py` and `sandbox_auth/http.py` already own live
  Pod/Sandbox resolution and strict single-bearer parsing, reused by Action Service, LLM ingress,
  and the egress rules API. `app/identity.py` instead admits ServiceAccount subjects or browser
  sessions with same-origin checks. Its bearer parsing and refusal semantics differ. Combining
  those paths would not be behavior-preserving. Operator OIDC/federation already reuse
  `mcp_infra/authentik_auth/oidc_principal.py`; keep workload and operator authority separate.
- **Clients:** `action_service/client.py` already shares request-time token acquisition and HTTP
  status handling in `_BearerClient`, including use by `app/action_federation.py`. The duplicated
  get/events methods keep workload and operator paths visible. `app/client.py` owns its HTTP
  client, accepts empty response bodies, and parses runner protobuf SSE; Action clients borrow
  HTTP clients and acquire a token per request. A common client would obscure these differences
  for little reduction.
- **Database fixtures:** `app/conftest.py` and `action_service/conftest.py` genuinely repeat the
  short database-name/admin-URL/create/drop sequence. Container startup and database operations
  already live in `util/testing/postgres_fixtures.py` and `util/testing/postgres.py`. The Action
  fixture applies migrations before yielding; the app store ensures its schema separately.
  Leave this small repetition rather than introducing a fixture layer coupling the two schema
  lifecycles. No cleanup or naming behavior is changed under the guise of extraction.
- **App test setup:** `app/test_api.py` seeds inventory and uses `TestClient`;
  `app/test_auth_routes.py` serves a real OIDC round trip with an event-loop-owned database pool;
  `app/test_action_api.py` composes canonical Action Service/federation/MCP and a second app/store
  to prove session survival across replicas. Shared dependencies already come from
  `app/conftest.py`, mock OIDC helpers, and `serve_app`. Repeated `create_app` calls expose the
  particular authority and replica under test, rather than duplicate a uniform fixture.

**Deferred:** reconsider an extraction when another consumer or an observed divergence gives one
of these small repeated sequences a concrete maintenance failure to prevent. This audit is not a
claim that the entire repository is duplicate-free, nor a production-readiness prerequisite.

## Decision-note wording

The task DAG's `DEL` acceptance text still claimed private operator-reason redaction despite its
landed decision-note section. Align that sentence with the existing API/BFF contract: human
`decision_note` is shared unchanged, and non-human provider reason evidence stays separate.
Before adding this audit, repository Markdown search found no literal `private_reason` or
`PUBLIC_REASON` wording.
The old column name in migrations and migration tests is necessary upgrade/downgrade evidence,
not stale wording to rename.

## Scope and proof

Only this audit and `x/agentplane/plans/task_dag.md` change. The DAG names `MCPFRONT` over the
canonical catalog/submit/get/events API, with `DEL` and durable external identity (`EID`) as
prerequisites and replacement edges to `MCPAGG`/`RETIRE_TOOLS`, independent of `MCP0`.
Validate the documentation diff, local links, graph references/dependencies, and repository
pre-commit hooks. No code extraction, schema change, dependency addition, live staging action,
or implementation of the deferred frontend/identity/OAuth/runtime tracks is included.
