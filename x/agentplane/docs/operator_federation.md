# Operator sessions and Action federation

## Implemented boundary

The app's existing routes remain unchanged. Its browser cookie now contains only a signed random
256-bit session handle. `operator_browser_session` in the **app database**, not the Action database,
holds Authlib's state/nonce/PKCE verifier while login is pending, then verified login issuer, stable
`sub`, display username, absolute deadline, and (only when Action federation is configured and its
lifetime is known) the access token. ID tokens and refresh tokens are not retained. Neither identity
nor OAuth/token material is encoded in the cookie. The row key is a SHA-256 digest of the handle.

The app follows its existing `TrajectoryStore.ensure_schema()` startup DDL pattern: it creates the
new table and expiry index with SQLAlchemy, under a PostgreSQL transaction advisory lock shared
by app startups. There is no separate app Alembic runner today. The Action schema is unchanged.
Existing signed-payload cookies are deliberately invalid after rollout: log in again. Replicas
must use the same app database, OIDC configuration, public origin, and session signing secret.

Login requires a verified signature, the exact configured issuer, a single audience naming the
login client (string or singleton list), a matching `azp` when present, and valid state/nonce/expiry.
Pending login expires after at most ten minutes. Authentication rotates the handle, deletes the
pending row, and consumes all OAuth state. Login lasts at most `AGENTPLANE_OIDC_SESSION_SECONDS`
(default eight hours), shortened to the verified ID-token expiry and retained access-token expiry.
There is no sliding renewal and no refresh grant: expiry requires another authorization-code login.
An access token without a known future expiry is discarded; federation then returns
`operator_reauthentication_required`. Browser login alone does not require an access token.

Each request re-reads its row. PostgreSQL row locking serializes same-session requests across
replicas through response headers (not the lifetime of an SSE stream). Callback rotation/logout
cannot be undone by an older request saving stale state. Logout deletes the entire row; cookie
replay then fails on every replica. Deleting a row also invalidates that session administratively.
Expired rows are rejected immediately and deleted on access; successful logins additionally clean
up expired rows. There is no background retention scheduler. Backups may retain expired credentials:
restrict DB/backup access accordingly. SQLAlchemy parameter logging is disabled for the app engine.
The database and its backups now contain credentials; use the existing encrypted storage and
restricted app DB role, not a read-only analytics role. No new encryption-key service is introduced.

Cookies remain HttpOnly, SameSite=Lax, and Secure with the `__Host-` name on HTTPS. Unsafe
session-authenticated requests, including logout, require an **exact** same-origin `Origin` header;
missing, trailing-slash, and foreign origins fail. Kubernetes-token callers keep their separate
non-ambient authentication and never enter the operator Action path. Responses are `no-store`. The app disables Uvicorn access logs to keep OAuth callback codes out of
request URLs in logs; callback failures use fixed messages without provider/query text.
Already-admitted requests/streams are not retrospectively cancelled by logout; revocation gates the
next request. Upstream account disablement is not polled; without a fresh login, the absolute expiry
is the browser identity lifetime. Token exchange may reject an upstream-revoked access token sooner.

## Explicit configuration required before deployment

**Not deployed by this PR.** No Action federation target/provider or corresponding network-policy
change is present in the checked-in staging deployment. Do not mount a shared BFF operator bearer,
forward a workload token, or invent a BFF signing authority to bypass this gap.

The existing Haku hostexec Authentik pattern is the supported exchange shape:
`grant_type=client_credentials`, `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer`,
and the current operator's login access token as `client_assertion`. No client secret is sent to the
exchange target. This is not RFC 8693 token exchange. Each request creates a fresh exchange client;
there is no mutable application-global operator-token cache.

To opt in, set the app's `action_federation` YAML key (or `AGENTPLANE_ACTION_FEDERATION` JSON) with
**all** these fields. Values below are descriptions, not deployable defaults:

- `service_url`: canonical Action Service base URL; use a trusted internal route or HTTPS.
- `token_endpoint`: Authentik's shared HTTPS token endpoint. Loopback HTTP is accepted for tests only.
- `login_jwks_uri`: pinned JWKS URI for the configured `AGENTPLANE_OIDC_ISSUER` login provider.
- `scope`: the exact reviewed federation scope set; no proxy-outpost `ak_proxy` scope by default.
- `target.issuer`: exact per-provider issuer of the new Action-only federation target.
- `target.audience`: that target's OAuth client ID, also required as `azp`.
- `target.jwks_uri`: its pinned HTTPS JWKS URI.
- `target.subjects`: non-empty reviewed allowlist of target-provider operator subjects.
- `subject_mapping`: non-empty mapping of login-provider `sub` to target-provider `sub`.
  All mapped targets must be in `target.subjects`. Establish mappings from authoritative Authentik
  identity evidence; do not assume provider-scoped subjects are identical or join by username.

Set the Action Service's `operator_oidc` YAML key (or `AGENTPLANE_ACTIONS_OPERATOR_OIDC` JSON) to
the same `issuer`, `audience`, `jwks_uri`, and `subjects` object as the app's `target`. Its legacy
`operator_bearer_file` adapter is mutually exclusive and is **not** a fallback for federation.
Partial/invalid configuration fails startup. A configured app federation without OIDC login also
fails startup. Changing reviewed mappings or allowlists requires a configuration rollout.

The Authentik target must explicitly trust only the Agentplane login provider through
`jwt_federation_providers`, use a short token lifetime, and emit signed RS256 access tokens with
`iss`, `sub`, `aud`, `azp`, `iat`, and `exp`. The shared resolver enforces these pins with its existing
30-second clock-skew allowance and five-minute JWKS cache. Exchange does not enforce the target
application login policy, so the destination's subject allowlist is mandatory. Configure network
reachability for BFF-to-token/JWKS/Action and Action-to-JWKS explicitly. No live cluster change or
live-provider claim-mapping validation was performed here.

Before enabling, validate the real target's subject mappings and token claims with two authorized
operators and a denied operator. The signed mock tests prove our request composition, verification,
and audit continuity, not the deployed Authentik policy. The BFF verifies the retained upstream
access token matches the current session's **issuer and subject**, then verifies the exchanged token
matches the explicit target subject. Action Service independently verifies and authorizes that token,
and records its actual target issuer/subject in the existing Decision issuer field.

## Failures are distinguishable and fail closed

- No browser session: 401. A workload caller asking for Action review: 403.
- Federation absent: 503 with `detail.code=operator_federation_not_configured`.
- Expired session: 401, re-login. No usable retained access token: 403 with
  `operator_reauthentication_required`.
- Unmapped operator: 403 with `operator_federation_subject_not_authorized`.
- Token/session or source/target subject mismatch: 403 with `operator_federation_identity_mismatch`.
- Signature/issuer/audience/azp/expiry/required-claim rejection: 403 with `operator_federation_token_invalid`.
- Exchange/JWKS/network/provider failure: 403 with `operator_federation_exchange_failed`.
  These are intentionally fixed public codes; provider bodies/exceptions and tokens are not returned.
- Destination rejection retains its HTTP status with the existing generic rejection message;
  destination transport failure remains 503 `Action Service is unavailable`, not a configuration error.

There is still one Action authority. Only Action **arguments** are exact in authenticated operator
list/detail/decision receipts. Caller/workload arguments remain recursively key-redacted; origin,
correlation, executor/provider errors and execution results retain the existing redaction policy.
A result echoing an argument does not become an operator credential-disclosure path.

## Evidence targets

- `//x/agentplane/app:test_action_api`: signed login, request-bound exchange, independent destination
  verifier, durable decisions, two app instances with distinct DB connection pools sharing PostgreSQL,
  callback on another replica, two operators with the same display name but different mapped subjects,
  logout replay rejection, wrong issuer/audience/expiry/subject rejection, and real MCP single dispatch.
- `//x/agentplane/app:test_auth_routes`: server-side PKCE/state, stable subject, expiry, logout and
  strict same-origin mutations, rejected signed login claims/signatures, state/nonce mismatch, handle
  rotation and callback replay, alongside the existing Kubernetes caller boundary.
- `//x/agentplane/action_service:test_operator_oidc`: actual operator API admission with signed
  wrong-issuer/audience/azp/expired/unauthorized/missing-sub/wrong-signature tokens.
- `//x/agentplane/action_service:test_acceptance`: exact operator arguments including nested
  secret-looking values, recursive caller redaction, and unchanged redacted execution results.

Agent-requested withdrawal/cancellation and an operator-authored **public** decision reason remain
unimplemented. They require separate decisions about cancellation races and public-versus-private reason delivery.
