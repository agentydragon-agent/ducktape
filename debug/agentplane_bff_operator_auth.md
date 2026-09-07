# Agentplane BFF → Action Service: operator identity gap

Source inspection: `upstream/devel` at `57afbdfd52da397442ea2ad448023be5f453e1de`,
2026-09-07, including merged #5777 and its Everything staging configuration.
No live cluster reads/edits or token exchanges were performed for this investigation.

## Finding

**An existing platform mechanism preserves the user; an Agentplane end-to-end
adapter does not yet exist.** Haku hostexec uses Authentik JWT-bearer federation,
not ordinary machine client credentials. Reuse that mechanism, but do not enable
Action review by mounting a static BFF bearer or forwarding a workload token.
A token-provider-only patch cannot bridge the current username-only session.
This note deliberately implements no authentication or deployment changes.

## Observed evidence

- [OIDC callback](../x/agentplane/app/auth_routes.py) uses Authlib's authorization
  code flow, pins the returned ID-token issuer, and stores only
  `user.username = preferred_username` in the session. It discards access/refresh
  tokens and `sub`. [OIDC settings](../x/agentplane/app/oidc.py) specify a signed
  cookie, eight-hour default session, `openid profile`, and no refresh/store.
  Signed cookies are not encrypted server-side credential storage.
- [BFF dependency](../x/agentplane/app/api.py), `_operator_actions`, admits only
  `CallerKind.OPERATOR`, then returns an application-global injected client; it
  does not pass the caller identity into its token provider.
  [Production main](../x/agentplane/app/main.py) supplies no `operator_actions`,
  so review returns 503 rather than authenticating as a different principal.
- [Action Service auth](../x/agentplane/action_service/auth.py) provides disabled
  and fixed file-backed bearer adapters. The latter always returns
  `configured-operator:<configured subject>` with role OPERATOR.
  [Production main](../x/agentplane/action_service/main.py) selects only those
  adapters. [API](../x/agentplane/action_service/api.py) separates operator and
  workload surfaces; [database](../x/agentplane/action_service/db.py) records a
  human decision's issuer as `principal.key`. A shared static bearer would
  therefore erase the browser operator from the durable decision identity.
- [BFF integration test](../x/agentplane/app/test_action_api.py) uses real mock
  OIDC login but a test-only fixed bearer downstream (`test-review-bff`). It
  proves the decision/dispatch seam, not operator identity continuity.
- [Staging login provider](../tf/gitops/sso-providers/provider_agentplane_staging.tf)
  is a confidential, per-provider-issuer authorization-code client. Its login
  policy admits Rai. There is no Action Service federation target there.
  [Action deployment](../cluster/k8s/agentplane-staging/actions/deployment.yaml)
  configures no operator adapter. Its [network policy](../cluster/k8s/agentplane-staging/actions/networkpolicy.yaml)
  admits BFF traffic but does not establish user identity or permit the JWKS
  network path a new verifier would need. Network reachability is not authz.

## Existing-platform path

[Hostexec Terraform](../tf/gitops/agent-machine-access/hostexec.tf) declares
per-target OAuth2 providers with `jwt_federation_providers` restricted to the
operator-login provider, per-provider issuer, target audience, one-minute token
lifetime, and operator group scope mappings. The
[console exchanger](../haku/console/tools/hostexec_token.py) sends
`grant_type=client_credentials` **with the acting operator's access token as a
JWT-bearer client assertion**. It sends no shared client secret. The
[request composition](../haku/console/mcp/in_process_servers.py) explicitly uses
`OPERATOR_LOGIN_IDENTITY`; the [destination verifier](../haku/hostexec/hostexecd/authentik.rs)
checks signature, issuer, audience, expiry, and the required host/run-as group,
and returns the operator subject for audit.

The [Authentik POC investigation](../x/authentik_mcp_poc/NOTES.md), §§4–7,
records that federation resolves `self.user = federated_token.user`. It also
records that exchange does **not** enforce the target application's login
policy: the destination must authorize the operator. Its provider allowlist and
stored-token lookup are significant; it is not generic acceptance of arbitrary
signed assertions. The checked-in [Authentik chart](../cluster/k8s/authentik/app/helmrelease.yaml)
is pinned to 2026.2.1; the investigation documents no RFC 8693 support for that
version. This is repository evidence, not a fresh live-provider verification.

The [shared exchanger](../mcp_infra/authentik_auth/token_exchange.py) is scoped to
proxy-outpost use (`ak_proxy`), so do not blindly reuse its scope set for Action
Service. The [OIDC principal resolver](../mcp_infra/authentik_auth/oidc_principal.py)
already validates exact issuer/discovery, RS256, audience, authorized party,
expiry/issued-at, and subject; it does not decide Action Service operator access.
The [mock exchange integration](../haku/console/test_mcp_token_exchange_integration.py)
asserts the original operator subject reaches a protected backend. Those tests
were inspected, not executed during this docs-only investigation.

## Options and recommendation

1. **Recommended — needed support: use the hostexec federation pattern.**
   Retain the authenticated operator's upstream access token server-side, bound
   to that session and verified issuer/subject, with an opaque browser handle.
   Reuse existing platform token-storage/refresh machinery where suitable;
   re-login on expiry is an acceptable first slice instead of adding refresh.
   Declare an Action-only exchange target trusting only the Agentplane login
   provider, then construct the client/token provider per request. Validate the
   exchanged token at Action Service with a pinned issuer, Action audience,
   algorithm, expiry and required claims. Explicitly authorize operator access
   there (reviewed subject allowlist or a narrowly mapped group), not merely
   any token signed by Authentik. Keep issuer/subject as durable identity and
   username only as display. Confirm subject mapping across providers rather
   than assuming provider-scoped subjects are byte-identical. This requires a
   session credential-lifecycle and target-authz contract, not just deployment
   wiring; those choices are not present in Agentplane today.
2. **Deferred — reuse the existing Haku Console operator boundary.** Route review
   through its retained operator-login identity and federation composition.
   This avoids a second credential lifecycle but expands the integration-app
   dependency and API ownership scope. Prefer it only if Console is intended
   to own this browser session already.
3. **Deferred — BFF-signed internal assertions.** A new BFF signing authority
   could assert subject plus actor with Action-only audience and short expiry.
   No supported instance was found in the inspected Agentplane/Haku auth paths.
   It adds key distribution/rotation and impersonation authority, so it is
   larger and less native than Authentik federation; do not implement it here.

## P0 behavior and proof required before enabling

Two independently logged-in operators A and B must produce distinct, correct
issuer/subject identities in Action Service decisions, including interleaved
requests. Exercise browser login → request-scoped exchange → actual Action API
verifier → durable decision with signed mock OIDC/JWKS, then separately validate
the deployed Authentik federation claim/policy behavior in an authorized test.
Reject wrong issuer/audience/signature, expired or missing tokens/claims,
unauthorized users, machine credentials and workload/Sandbox principals. A user
outside the target authz policy must fail even if exchange succeeds. Logout and
upstream-token expiry must never fall back to BFF identity. Preserve the existing
single-dispatch/idempotency and caller-private-data boundaries.

**Current result:** browser identity is established at the BFF, but is not
preserved end-to-end into production Action review because that connection
remains unconfigured and fail-closed. The fixed-bearer test is not evidence of
identity preservation. No speculative authentication was shipped.
