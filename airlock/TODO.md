# Airlock TODOs

## Multi-Item PlaidProvider

Plaid's data model is N Items (institution logins) per client_id+secret —
each Item gets its own permanent access_token. Airlock's current
provider model stores **one** access_token per provider name, so the
workaround for multiple banks is one airlock provider per institution
(`plaid_chase`, `plaid_bofa`, …). That sprawls:

- Config: every new bank needs a provider stanza + duplicated env vars
  (`PLAID_<NAME>_CLIENT_{ID,SECRET}`) pointing at the same shared
  `plaid-client-credentials` Secret.
- Plaid dashboard: every provider needs its own redirect URI added to
  Allowed redirect URIs (`/oauth/callback/{provider_name}`).
- UI: the providers list grows linearly with linked institutions, even
  though "Plaid" is conceptually one thing.

Refactor so **a single `plaid` provider holds N linked Items**, scoped to
the Plaid provider_type only — `GenericOAuth2Provider` (Oura, Google)
stays one-token-per-provider, since those identity providers don't have
multi-Item semantics.

### Shape

- Storage: keep `plaid-client-credentials` shared. Replace
  `plaid-{access-token,tokens}` singletons with per-Item Secrets keyed by
  `item_id` (e.g. `plaid-item-<item_id>-{access-token,tokens}`) — or a
  single JSON map secret. Whichever fits the K8sTokenStore cleanup model
  better (label-based sweep needs an exhaustive `known_names`; a per-Item
  naming pattern with a tracked index secret is easier to reason about
  than a single mutable blob).
- `PlaidProvider`: becomes a container holding `dict[item_id, TokenData]`
  plus per-Item metadata (institution_id, linked_at, account names
  cached from `/accounts/get`). New methods: `list_items()`,
  `add_item(public_token)`, `remove_item(item_id)`.
- `oauth/routes.py`: one shared redirect URI (`/oauth/callback/plaid`).
  Drop provider-name-from-path dispatch for Plaid; look up the right
  provider via the `oauth_state_id` airlock already stores server-side
  (the state record carries the provider it was created for). Means
  exactly **one** URI in the Plaid dashboard regardless of bank count.
- `/api/oauth/providers`: for Plaid, return one provider with a nested
  list of `PlaidItemStatus { item_id, institution_id, linked_at,
account_summaries }` instead of a single connected/disconnected flag.
- Frontend: under the Plaid row, render the list of linked institutions
  with per-Item unlink buttons + one "Link new bank" CTA that runs the
  Plaid Link flow and appends to the list (instead of overwriting).
- Migration: read existing per-institution providers (`plaid_chase`,
  `plaid_bofa`, …), fold their tokens into the new multi-Item `plaid`
  provider keyed by `item_id`, then prune the old config stanzas.

Single landing of this + cleanup of the dashboard URIs is the right end
state. Cross-cutting follow-up to the per-institution workaround introduced
in `cluster/k8s/agents/airlock/config.yaml`.

## OIDCProxy follow-ups

MCP OAuth via `MultiAuth(OIDCProxy + JWTVerifier)` is implemented. Remaining items:

### Per-user isolation

Track the JWT `sub` claim on actions for multi-user separation. Currently only `client_id`
is stored. When multiple Authentik users access airlock, their actions should be scoped
so each user only sees their own. Low priority while only one user (agentydragon) exists.

### Client identity in Svelte UI

Show `client_id` on actions in the operator SPA. The field is stored in the DB and
returned by the REST API — the frontend just needs to render it.

### Well-known protected resource metadata

`/.well-known/oauth-protected-resource` returns 404 under the `/mcp` mount. The ASM
endpoint (`/.well-known/oauth-authorization-server`) works. Investigate whether this is
a FastMCP routing issue or if the path needs to be different. Claude.ai may not need it
(it follows the `resource_metadata` URL from the 401 `WWW-Authenticate` header).

## Capability token grant system

Allow agents to request temporary or permanent capability grants, which are approved
by the human operator and encoded as tokens the agent can present on subsequent calls.

### Flow

1. Agent calls a special airlock tool (e.g. `airlock_request_grant`) with a description
   of the capability it wants (e.g. "run commands matching `kubectl get *`").
2. Airlock queues the grant request for operator approval (same UI as normal actions).
3. Operator approves → airlock issues a signed token encoding the granted capability.
4. Agent receives the token and presents it in future tool calls (e.g. via a
   `grant_token` parameter or a dedicated header/field).
5. Predicate/policy layer checks the token and returns `Approved` without requiring
   another human decision.

### Token design options

- **Signed JWT claims**: Token is a JWT signed with an airlock server secret.
  Claims encode the capability scope (namespace, tool pattern, argument constraints),
  issuing time, and optional expiry. Stateless — airlock just verifies signature + claims.
- **Stateful grant records**: Airlock stores grant records in the DB (like actions).
  Token is an opaque ID referencing the record. Supports explicit revocation.
- **Hybrid**: JWT with a JTI claim; DB stores revoked JTIs for revocation support.

### Capability scope representation

Grants should be able to express:

- Which backend namespace(s) and tool(s) the grant applies to.
- Optional argument-level constraints (e.g. read-only commands, specific paths).
- Temporal constraints: expiry time, or "one-shot" (consumed on first use).
- Optional human-readable label shown in the approval UI.

### Predicate integration

The predicate function (or a new pre-predicate hook) receives the presented grant
token alongside `(server_namespace, tool_name, arguments)` and can return `Approved`
if the token matches and is valid. The existing `NeedsHumanDecision` / `Denied` paths
are unchanged for calls without a valid token.

### Implementation sketch

- New DB table `grants` (id, created_at, expires_at, scope_json, revoked).
- New MCP tool `airlock_request_grant(description, scope)` exposed to agents.
- `proxy_server.py`: extract optional `grant_token` from tool call arguments before
  forwarding; validate token against DB / JWT signature; short-circuit to `Approved`
  if valid.
- Frontend: grant requests appear in the action queue; approval issues the token and
  returns it to the waiting agent call.
- Config: `grant_signing_secret` (for JWT mode) or toggle between stateful/JWT modes.
