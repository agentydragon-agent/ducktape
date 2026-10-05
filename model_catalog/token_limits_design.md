# Model limits, serving configuration, and client budgets

Status: design proposal and investigation record, 2026-10-05. No route retirement
is approved by this document. Implementation and validation are incomplete.

This document separates what we know, what we configure, and what clients infer.
It is the decision record for the roster/limits work, not another runtime source
of model numbers. Code owns executable configuration; this document explains its
constraints, provenance, and unresolved choices.

## Contents

- [Scope and priorities](#1-scope-and-priorities)
- [Vocabulary](#2-vocabulary-numbers-that-must-not-be-conflated)
- [Ownership and data flow](#3-ownership-and-data-flow)
- [LiteLLM catalogue and publication](#4-litellm-catalogue-overrides-and-publication)
- [Client-specific values](#5-client-specific-values-and-semantics)
- [Ollama serving configuration](#6-ollama-serving-configuration)
- [Other projections](#7-additional-projections-and-side-effects-to-inventory)
- [Proposed shape and rollout](#8-proposed-shape-after-reducing-scope)
- [Operator decisions](#9-decisions-requested-from-the-operator)

## 1. Scope and priorities

The operator's currently used paths are:

1. Agentplane → Codex harness → LiteLLM → Codex/ChatGPT subscription API
   (through our subscription gateway).
2. Claude Code Web → upstream provider, without our LiteLLM.
3. Local Codex and Claude Code → upstream providers directly.

Preserve these. Moving more clients behind central LiteLLM is a desired future
capability, not permission to migrate the direct clients now. Supporting every
historical model × account × wire × harness combination is **not** a requirement.
Unused wrappers and integrations may be paused or retired after confirmation.

### Desired properties

- One neutral source of route identities, account identities, names, and established
  serving-path facts. Nix and cdk8s both consume it; neither owns the other.
- Explicit consumer choices. Being served, being authorized, being offered in a
  picker, and being the default are different decisions.
- Known input/output limits are a justified complete pair, or absent. Absence must
  not silently become a claim about an unrelated upstream API.
- Client compaction budgets and serving settings have explicit owners. A setting
  does not become a capacity fact merely because several clients use the number.
- Consistent advertised limits across equivalent wires for the same serving path.
  Real differences are allowed, but must be justified rather than inherited from
  adapter-name heuristics.
- Fewer active combinations, fewer lines of plumbing, and tests of actual boundary
  behavior. Prefer deleting an unused projection to building a generalized framework.
- cdk8s configuration/manifests remain Bazel-visibility restricted. Runtime services
  receive serialized configuration, not imports of deployment generators.

### Non-goals

No universal `context_window` field, universal client-budget object, duplicate model
registry, automatic equation between `num_ctx` and input/output limits, or promise
that every client interprets a field identically. No broad LiteLLM fork or middleware
framework just to preserve unused routes. Do not remove billing metadata while
fixing token-limit publication. Keep independent refactors out of #8899, whose scope
is the runner context-size endpoint.

## 2. Vocabulary: numbers that must not be conflated

| Concept | Meaning | Does not establish |
| --- | --- | --- |
| Provider input ceiling | Input accepted by this account's serving path, under documented conditions | Combined input/output capacity |
| Provider output ceiling | Output ceiling on that path; treatment of reasoning tokens is provider-specific | How much output remains after a particular prompt |
| Combined context capacity | Tokens jointly retained/attended, with backend-specific accounting | An independent maximum input and maximum output pair |
| Client context budget | Client assumption used for accounting, reserves, and compaction | Backend capacity or successful long-context quality |
| Request output budget | Generation limit sent with one request | Model capability metadata |
| Ollama `num_ctx` | Requested runtime context allocation | Proven attended capacity or an output ceiling |
| Ollama `num_predict` | Generation-length option | Context allocation |
| Reported harness window | Harness's resolved view of its context budget | Measurement of what the backend actually attended |

Even a justified input/output pair need not mean that both maxima can be attained
simultaneously. Record any combined constraint in the evidence; do not invent
`combined = input + output`, or derive input by subtracting a client output setting.
If an active path needs a combined constraint enforced, design that explicitly.

`model_info.max_tokens` is legacy **metadata**. Request-body `max_tokens` is a
**generation setting**. Removing the former must not remove the latter.

## 3. Ownership and data flow

| Owner | Defines | Consumers / serialization boundary |
| --- | --- | --- |
| `model_catalog/catalog.py` | Account/model facts, named routes, outbound adapters, aliases | Nix and cluster generators |
| `model_catalog/policies.py` | Allowed routes plus ordered fallbacks in one lane record | Virtual-key/team configuration; not implicit picker policy |
| `cluster/cdk8s/litellm/` | Endpoint/auth bindings and LiteLLM projection | Generated proxy config |
| Ollama deployment and model definitions | Server defaults, model tags/aliases, runtime serving options | Ollama; route must resolve to the intended model definition |
| `model_catalog/nix.py` and Nix gateway modules | Wrapper route selections and Claude-specific settings | Generated wrapper JSON → process environment |
| `cluster/cdk8s/public_coder_agent_config.py` | OpenClaw model selections and client budgets | OpenClaw configuration |
| `cluster/cdk8s/model_selections.py` | Agentplane offers and explicit runner budget selections | App catalogue and runner configuration |
| Agentplane runner adapters | Applying configuration in each native harness's vocabulary | Claude environment / Codex startup options |
| Native harness | Reserves, compaction, metadata recognition, reported usage | Actual request construction and native telemetry |

Account is not manufacturer; outbound wire is not the client-facing wire. A Claude
harness can send Anthropic Messages to LiteLLM while LiteLLM sends Responses upstream.
Equivalent model-name suffixes do not establish equivalent accounts or capacities.

Use named `Route` references until serialization. Define named routes first and
assemble rosters from them. Do not recover identity through positional unpacking,
parallel maps, or parsing the last segment of a slug.

## 4. LiteLLM: catalogue, overrides, and publication

### Evidence scope

The proxy's package-local lock and upstream image pin are LiteLLM **1.100.1**.
The root Python lock is not the proxy runtime. Relevant upstream source files are
`utils.py`, `router.py`, `proxy/proxy_server.py`,
`litellm_core_utils/get_model_cost_map.py`, and `llms/ollama/common_utils.py`.
The wheel's `model_prices_and_context_window_backup.json` and the
[remote catalogue](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)
were inspected separately. The remote snapshot below was fetched 2026-10-05.

Unless configured otherwise, LiteLLM downloads the remote catalogue; the bundled
file is a fallback. `LITELLM_LOCAL_MODEL_COST_MAP=True` selects the bundled map.
Pinning the package alone does **not** pin the catalogue. Neither source is evidence
for our subscription gateway's limits.

### What happens to metadata

1. LiteLLM resolves `litellm_params.model`, including its adapter prefix, against
   catalogue candidates with provider-compatibility checks.
2. Exact misses can use catalogue regex generalizations. Native Ollama may query
   `/api/show`; there is more than a static JSON lookup involved.
3. Deployment `model_info` registers/merges overrides into LiteLLM's model-cost map.
   This map contains both capacity/capability and pricing metadata.
4. Router objects and metadata endpoints perform further serialization and merging.
   List and single-deployment `/model/info` paths are not identical.

Omitting a key permits fallback. Explicit YAML `null` is **not a reliable deletion
operator**: `register_model()` uses `_update_dictionary()`, which ignores `None`;
router serialization uses `exclude_none=True`; the single-deployment metadata
endpoint removes nulls before filling missing keys. The final response merge alone
is therefore insufficient evidence that null suppression works.

This is a source-traced finding, not a completed end-to-end null-config test. That
experiment remains a prerequisite for any chosen publication implementation.

### Token KVPs in the remote catalogue

These are catalogue defaults, **not our serving-path facts**. Values are tokens.
Other catalogue KVPs include mode, pricing, caching rates, and capability flags;
those need separate treatment, not deletion alongside limits.

| Matching model family / adapter | `max_input_tokens` | `max_output_tokens` | `max_tokens` |
| --- | ---: | ---: | ---: |
| OpenAI GPT-6 Astra/Sol/Luna; GPT-5.6 Sol/Terra/Luna | 922000 | 128000 | 128000 |
| OpenAI GPT-5.4 / GPT-5.5 | 1050000 | 128000 | 128000 |
| Anthropic Opus/Sonnet/Fable 5; Sonnet 4.6 | 1000000 | 128000 | 128000 |
| Anthropic Haiku 4.5 | 200000 | 64000 | 64000 |
| Google Gemini 3.7 Flash / 3.5 Flash Lite | 1048576 | 65536 | 65536 |
| Google Gemini Embedding 2 | 8192 | absent | 8192 |
| Google Gemini Embedding 001 | 2048 | absent | 2048 |
| Mistral Codestral / code / code-FIM | 128000 | 128000 | 128000 |
| Mistral Magistral, Ministral 8B/14B, medium/small/vibe routes | 262144 | 262144 | 262144 |
| Mistral Ministral 3B | 131072 | 131072 | 131072 |
| Mistral Voxtral Small | 32768 | 32768 | 32768 |
| Groq Whisper | absent | absent | absent |

The bundled catalogue differs: GPT-6 entries are absent; Magistral has all three
values at 40000; `mistral-medium` has input 32000, output/legacy 8191. Bundled Groq
Llama 3.3 70B has 131072/32768/32768, and Llama 3.1 8B has all three at 131072;
those exact entries are absent from the remote snapshot.

Additional cases:

- `openai/gpt-*` can use OpenAI entries. `anthropic/gpt-*` fails that provider match.
- Antigravity `anthropic/gemini-*` does not simply inherit Google entries; its
  `anthropic/claude-sonnet-4-6` can inherit Anthropic's raw-API entry.
- A Claude-family regex supplies input 200000, output 64000, legacy 64000 even
  without an exact entry. It matches our Tana Claude names and the Antigravity
  `claude-opus-4-6-thinking` name.
- Our exact local Ollama tags lack static entries. Native discovery can read recorded
  `context_length` from `/api/show` and put it into **all three** token-limit fields.
  That is not a measured output ceiling or necessarily the effective `num_ctx`.
- `context_window` is not a standard catalogue field used by this projection. Our
  former custom field should not be smuggled back in as a generic client budget.

### Observed deployed mixture

On 2026-10-05, `/model/info` under the cheap-experiments key returned:

| Luna route | Input | Output | Legacy |
| --- | ---: | ---: | ---: |
| `chatgpt/ant-messages/gpt-6-luna` | 372000 | 128000 | null |
| `chatgpt/oai-responses/gpt-6-luna` | 372000 | 128000 | 128000 |

These responses contain existing overrides. They are not pristine catalogue
lookups, and the restricted key does not establish the state of every deployment.

### Who consumes these KVPs?

- `/model/info` clients and the LiteLLM dashboard see published metadata.
- LiteLLM itself can use the model-cost map for token checks and output adjustment,
  not only display. For example, `get_modified_max_tokens()` uses catalogue-derived
  maxima, and I/O token-rate checks can fall back from `max_output_tokens` to
  `max_tokens`. Whether a specific check runs depends on configuration/call path;
  an internal reader does not prove it is enabled on our active path.
- OpenClaw's audited discovery reads `/v1/models` or `/models`, not `/model/info`.
  Its configured budgets come from our OpenClaw projection.
- Our Agentplane launch adapters do not obtain their context overrides from
  `/model/info`. They read runner-owned configuration.
- Claude and Codex have their own model recognition/catalogues. Removing a LiteLLM
  metadata key does not remove a harness's built-in assumption.

Therefore response filtering and changing LiteLLM's internal catalogue are different
changes. Do not solve one by silently changing pricing or request behavior in the other.

## 5. Client-specific values and semantics

Numbers below are preserved configuration choices at draft #9034 head `26862c4395`,
not newly validated provider limits and not a claim that the draft is deployed.

The draft retains a provider limit pair only for the direct Google Gemini models:
1048576 input / 65536 output, based on provider documentation. Historical GPT-5.6
subscription probing accepted 370629 input tokens and rejected 372194; it did not
establish an output ceiling or a combined capacity. The 372000 client budget is
not that complete contract. Astra's 872000 came from Codex client metadata; Sol/Luna
inherited earlier budgets rather than independent probes. Antigravity's upstream
`maxTokens` semantics were ambiguous. Those are reasons to leave provider facts
unset, not reasons to quietly fall back to raw-API catalogue facts.

### Claude Code wrappers

`model_catalog/nix.py` → `claude-wrappers.json` →
`nix/home/claude_code/gateway.nix` maps:

- `maxContextTokens` → `CLAUDE_CODE_MAX_CONTEXT_TOKENS`.
- `maxOutputTokens` → `CLAUDE_CODE_MAX_OUTPUT_TOKENS`.

| Wrapper | Context setting | Output setting |
| --- | ---: | ---: |
| `codex-claude` (Astra primary / Luna small model) | 872000 | 128000 |
| `gemini-claude` | 1048576 | 65536 |
| `antigravity-claude` | 1048576 | 65536 |
| `litellm-claude` | omitted | omitted |
| `tana-claude` | omitted | omitted |

In the inspected Nix Claude Code **2.1.283**, the context override is an assumed
pre-reserve window for custom models; recognized model metadata can take precedence.
The normal observed compaction calculation subtracts an output reserve capped at
20000, then 13000 headroom. Other overrides and execution modes can alter this.
It is neither a plain max-input ceiling nor a universal backend context capacity.

`litellm-claude` also uses a `[1m]` name suffix as a **Claude client convention**.
The suffix is stripped before sending the model name upstream. Switching models
through gateway discovery can lose that convention. Do not create duplicate served
routes merely to encode a client's suffix convention.

Claude Code Web and direct local use must not inherit these gateway overrides just
because they use the same model family. Also, the Agentplane harness-test archive
is **2.1.252**, not 2.1.283: recheck the actual launched package before relying on
version-specific formulas.

### OpenClaw

Audited version: **2026.9.5**, source revision
`ec9c1a13db8938e5a3eaa51fca2e981cde2395a9`.
`contextWindow` is the pre-reserve client context budget; runtime `contextTokens`
can narrow it. Compaction uses `contextWindow - reserveTokens`, with additional
history/pending-input accounting. The core default reserve is 16384; agent policy
raises the floor to 20000, subject to a 25% window cap. It does **not** generally
reserve the full `model.maxTokens`. `maxTokens` is separate output/request metadata.

The public-coder projection currently preserves:

| Selection | `contextWindow` | `maxTokens` |
| --- | ---: | ---: |
| GPT-6 Astra | 872000 | 128000 |
| GPT-6 Sol / Luna | 372000 | 128000 |
| Direct Google Gemini routes | 1048576 | 65536 |
| Antigravity Claude Opus / Sonnet | 200000 | 64000 |
| Antigravity Flash group | 1048576 | 65536 |
| Antigravity Pro / Pro Low / Flash Lite 3.1 | 1048576 | 65535 |
| Antigravity GPT-OSS 120B Medium | 114000 | 32768 |

The 65535/65536 difference is preserved history, not an established distinction in
provider capacity. The 114000 value is an OpenClaw budget, **not** both a provider
input ceiling and a combined context window. Whether to keep this integration at
all should be decided before validating its entire matrix.

### Codex and Agentplane

Agentplane receives a route-ID-to-budget map through runner configuration
(`model_context_windows`, including the environment and guest-config inputs).
The current cluster override selection is only Qwen IQ4_XS 128K/256K, both wires:
131072 and 262144 respectively. The active GPT subscription routes do **not** receive
872000 or 372000 from this map merely because a wrapper or OpenClaw uses those values.

- Claude adapter sets `CLAUDE_CODE_MAX_CONTEXT_TOKENS` when an override exists.
- Codex adapter passes `model_context_window` in its startup configuration. Our
  launch helper leaves auto-compaction at Codex's derived default; its comment
  records 90%. Codex also has its own effective-window and metadata rules: do not
  treat that comment as an end-to-end validated threshold for every current binary.
- Changing a model to one with a different configured window, including an absent
  versus present override, requires a new thread. The runner rejects that live switch.
- Harness telemetry is another output: Codex reports
  `thread/tokenUsage/updated.tokenUsage.modelContextWindow`; Claude result frames
  report `modelUsage[*].contextWindow`. Acceptance probes record these as harness
  observations, not backend capacity measurements.

The existing [harness metadata audit](../agentplane/docs/model_metadata.md) documents
another dependency: Codex model-name recognition can enable tool modes, transport
preferences, and prompt behavior in addition to a window. Its inspected 0.152.0
version recognized only certain namespace shapes. Our hidden Astra alias exists
for recognition compatibility; deleting or renaming it is not just UI cleanup.
That historical audit also found fallback context/max-context of 272000, a 95%
effective-window factor, and a real Luna max-context of 872000. Its config override
was clamped by the recognized entry's maximum. These are version-scoped observations,
not new roster facts or promises that setting a larger number will take effect.
Verify the actual active Agentplane slug/alias and launched Codex version before
changing that path. The archive used by a test is not proof of the deployed binary.

Long-term, runner budgets must be harness-specific at the configuration boundary
if both harnesses need overrides. Do not add a universal budget record now to keep
an unused Claude-through-LiteLLM matrix alive. First decide which paths survive.

## 6. Ollama serving configuration

The inspected live/source version was **0.34.4**. Our deployment sets
`OLLAMA_CONTEXT_LENGTH=131072`; the Qwen 256K model alias bakes in `num_ctx=262144`.
See the [Ollama deployment notes](../cluster/cdk8s/ollama/README.md).

- `num_ctx` requests runtime context allocation. On the inspected GGUF path, the
  scheduler can clamp it to recorded training context. Allocation, prompt handling,
  and model quality are different evidence.
- `num_predict` controls generation length. The OpenAI-compatible `max_tokens`
  request field maps to it. It is not LiteLLM's `model_info.max_tokens`.
- Native Ollama requests can carry `options.num_ctx`. The OpenAI-compatible wire
  ignores that native option; a model alias/definition must select the context there.
- Server defaults, model-definition options, and request options are separate
  precedence layers. Inspect the effective loaded runner, not just our route name.
- Truncation/context shifting can allow successful requests without retaining all
  input. A short tool call or accepted long prompt does not prove attended capacity.

Do not auto-project `Route.num_ctx` into provider limits or every harness's budget.
Audit whether each retained variant changes actual serving behavior. In particular,
other GPT-OSS variants must not be considered validated just because Qwen's 256K
alias is wired. Pausing unused variants avoids preserving a misleading matrix.

## 7. Additional projections and side effects to inventory

Before deletion or renaming, check these as well as the obvious clients:

- Terraform virtual-key allowlists, team fallback order, and experiment keys.
- Agentplane picker/default selections, LLM ingress metadata/auth routing, and
  runner environment/guest configuration. These are not interchangeable registries.
- Hidden Codex recognition aliases and the public embedding compatibility alias.
- OpenClaw durable memory: stored embedding identities can outlive a running agent.
  Pausing the app is not permission to delete/rebuild its index or change its model.
- Parked Haku OpenClaw's native CLI model aliases, Gatus's selected Ollama probe,
  inference/probe scripts, and live harness acceptance cases.
- Nix wrapper JSON, binaries, imports, and credential provisioning. Moving a source
  file to `x/` alone does not stop deploying its generated outputs.
- LiteLLM pricing/budget accounting and telemetry labels. Route cleanup must not
  accidentally bypass spending limits or relabel unrelated account costs.

This is a starting inventory, not a claim of exhaustive runtime reachability.
Repository references and operator confirmation are both needed.

## 8. Proposed shape after reducing scope

Keep the existing small separation, rather than adding a meta-configuration layer:

1. **Neutral facts and identities:** `Model(..., limits=TokenLimits(input, output)
   | None)`, explicit `Upstream`, named `Route`, and aliases referencing routes.
   Provider input/output facts carry evidence in nearby documentation/comments.
   Unknown remains unknown. No generic model `context_window`.
2. **Serving configuration:** endpoint/auth bindings remain deployment-local;
   self-hosted runtime options are explicit and tied to real model tags. The neutral
   roster must not import cdk8s. No automatic serving-option-to-capacity conversion.
3. **Consumer configuration:** each retained consumer selects routes and owns its
   own budget vocabulary. Claude wrapper settings stay with wrappers, OpenClaw
   settings with OpenClaw, Codex launch policy with its runner adapter/configuration.
   Values can deliberately differ; sharing a number is not a reason to share semantics.
4. **LiteLLM publication:** implement one narrow, tested policy at the proxy boundary,
   only after selecting the supported paths. For generative models, publish our
   established input/output pair together or neither; do not publish the legacy
   `max_tokens` or custom `context_window` as independent competing capacity facts.
   Explicitly separate embedding/transcription metadata rather than inventing an
   output ceiling to satisfy a generation-only pair rule.
5. **Native client behavior:** configure and verify the actual harness. A clean
   `/model/info` response cannot fix Codex/Claude's independent recognition tables.

Item 4 is the desired contract, **not a solved implementation**. First test whether
an upstream-supported configuration mechanism can satisfy it through registration,
reload, list and single-deployment endpoints. If not, compare a small upstream fix
or targeted response projection against leaving LiteLLM's endpoint explicitly
non-authoritative. The latter does **not** satisfy the requested public pair-or-none
contract and requires an explicit decision, not silent acceptance. Avoid global
model-cost mutation or a broad wrapper service as a premature solution.

Internal catalogue use also needs an explicit decision: suppressing fields in an
HTTP response does not suppress LiteLLM's request-side limit heuristics. Determine
which checks execute on the retained path before changing them; preserve accounting.

### Rollout and useful validation

1. Agree which integrations can pause; keep the active subscription/Responses path
   and direct clients working. Remove unused projections and generated wiring first.
2. Record the active route, alias, harness version, actual model recognition, and
   resolved budget. Separate historical assumptions from evidence.
3. Finish the narrow LiteLLM publication experiment using the proxy-local pin, both
   bundled and controlled remote catalogue fixtures. Check load/reload and both
   metadata endpoint shapes, with a known pair, unknown limits, and legacy fallback.
4. Verify retained harness startup arguments/environment and reported window with
   a bounded request. Test model switching where budgets differ. Test Ollama alias
   effectiveness only for variants we decide to keep. No silent live deployment.
5. Regenerate artifacts, run exact-head checks, and then adapt #8899 separately.

Do not build a test matrix for every retired combination. A real config-loader/API
contract test pays rent; assertions that merely repeat every roster constant do not.
Keep the overall refactor net-negative in code/plumbing where possible.

## 9. Decisions requested from the operator

No removals below are authorized yet. Proposed order, by simplification benefit:

1. **Pause Nix Claude gateway wrappers:** `codex-claude`, `gemini-claude`,
   `antigravity-claude`, `tana-claude`, and `litellm-claude`? Keep ordinary direct
   Claude/Codex installations. This removes wrapper-specific budgets, suffix tricks,
   and model JSON generation from the immediate compatibility requirement.
2. **Pause OpenClaw public-coder and leave Haku OpenClaw parked?** Preserve durable
   state and embedding identities. This removes the second major client-budget
   vocabulary from the immediate rollout, without claiming it will never return.
3. **Retain only Agentplane Codex → subscription Responses as the supported gateway
   path for now?** In particular, may Agentplane Claude → LiteLLM and GPT-through-
   Anthropic-Messages be disabled? Keep Claude Code Web and direct local use intact.
4. **Which experimental backends must remain usable now?** Options to confirm:
   Ollama Qwen 128K/256K; other Ollama families/variants; direct Google; Antigravity;
   Tana; Mistral; Groq. An authorized experiment key does not mean every route must
   stay offered or actively maintained. Identify monitoring and embedding dependents
   before withdrawing any service.

For a paused integration, prefer removing active imports, selections, generated
outputs, and obsolete tests, relying on Git history for restoration. Use `x/` only
when keeping a runnable experiment is useful; do not copy the whole plumbing there
and continue generating it. Retire a route only after checking other consumers,
key/fallback references, aliases, and persistent identities.
