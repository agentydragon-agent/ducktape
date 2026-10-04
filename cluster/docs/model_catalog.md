# Served-model catalog

`cluster/cdk8s/model_rosters.py` owns the model metadata and served routes.
`cluster/cdk8s/model_selections.py` owns key, picker, and harness-override selections.
These are generation-only Python modules, not runtime application dependencies.

## Ownership

- `Model` describes a model **as served by its account**: upstream identity, known
  display name, context/output limits, and reasoning capability. Unknown metadata is
  unset. The declaration's comments retain the evidence and its limitations; a
  configured Ollama context is not proof of attended capacity.
- `Upstream` associates an account with its adapter, outbound protocol, endpoint, and
  credential reference. The shape comes from the adapter/protocol, not a second
  independently authored value. It is not the client's inbound protocol.
- `Route` associates those values with the actual upstream model/tag, exposed identity,
  and route-specific reasoning options. Consumers read `route.id`; they do not provide
  the provider/shape/model ingredients again.
- `RouteAlias` references a canonical route. The embedding compatibility identity and
  hidden Codex recognition alias retain their existing behavior.

The same upstream slug can identify different routes and limits through different
accounts. A route's context variant and upstream tag are bound together in the catalog.
Do not join metadata using a route's trailing string segment.

Missing names fail when a route is offered in the app, rather than being synthesized
from slugs. Missing limits remain unknown. `publish_limits` preserves which routes
currently override LiteLLM's metadata; knowing a limit does not automatically authorize
changing proxy behavior or applying a harness context override.

## Projections

| Consumer               | Input                                            | Output                                                     |
| ---------------------- | ------------------------------------------------ | ---------------------------------------------------------- |
| LiteLLM                | `SERVED_ROUTES`, `HIDDEN_ALIASES`                | Proxy config and alias settings                            |
| Terraform virtual keys | `KEY_MODEL_ROUTES`                               | Existing `model_allowlists` variables                      |
| Agentplane app         | `HarnessRoutes`                                  | App-owned `ModelCatalog` records and harness ID lists      |
| Agentplane environment | Same `HarnessRoutes`                             | Structured source retained for ingress metadata generation |
| OpenClaw public coder  | `PUBLIC_CODER_MODELS`                            | OpenClaw IDs, names, limits, and reasoning flags           |
| Parked Haku OpenClaw   | Selected subscription routes and command aliases | Native Claude Code model slugs                             |
| Gatus                  | Selected Ollama route                            | Probe request model ID                                     |
| Runner configuration   | `RUNNER_CONTEXT_OVERRIDES`                       | Existing context-window override map                       |

For example, a preset chooses `GPT6_LUNA_RESPONSES`; the app renderer emits its ID,
display name, and reasoning choices. The key renderer emits only its ID. Neither knows
how to construct a ChatGPT Responses route name.

Authorization and picker policy are intentionally distinct. An Ollama key admits both
wires while the Agentplane picker offers only the OpenAI-compatible route. Adding a
served model does not necessarily add it to a picker or a restricted key. Defaults
remain explicit consumer choices referencing existing routes.

## Remaining migrations

Python consumers select route objects. OpenClaw's account labels and parked Haku's
command aliases remain presentation specific to those consumers. The public-coder
catalog excludes routes with unknown limits; the renderer rejects missing metadata.
The runner's override selection remains limited to Qwen IQ4_XS, even though other
routes have known or configured context windows.

`CLAUDE_WRAPPER_MODELS` projects to
`cluster/generated/model-clients/claude-wrappers.json`, read by the Nix wrappers as
gateway options. `KEY_FALLBACK_ROUTES` projects to the Terraform CR's `model_fallbacks`
input. Both selections are checked against their key allowlists. Regenerate these
artifacts with `bb run //cluster/cdk8s:generate_manifests`.

Claude's `[1m]` request convention stays in `litellm-claude.nix`, separate from the
served ID. The Antigravity wrapper explicitly retains its configured 65,536 output
override, while the account metadata remains 65,535. Changing that policy requires a
separate behavioral change; do not replace account metadata with a borrowed Google API
limit.

The ingress follow-up should consume `Environment.model_routes`, not extract IDs from
`app_config` and look them back up. It must preserve the distinction between metadata
availability and the existing, deliberately narrow runner override policy.

Runtime services own their configuration/API schemas and consume serialized data;
they must not import this catalog. Diagnostic probes and acceptance tests likewise
consume generated configuration or deployed APIs.

## Checks

The focused tests compare the LiteLLM and Agentplane projections to committed
ConfigMaps, and check route uniqueness, alias targets, canonical selection references,
key/picker boundaries, and unknown-metadata behavior. The whole-tree manifest parity
test also covers the Terraform key inputs and the remaining consumers. Do not replace
these checks with a second handwritten model inventory.
