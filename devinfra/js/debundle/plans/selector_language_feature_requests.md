# Selector Language Feature Requests From Gaffer P4

This note collects feature requests from the 2026-06-22 `tana/re/web`
selector-stabilization dispatch in `gaffer-private`. It is deliberately framed
as selector-language and synthesis work, not as a replacement for the relational
resolver. The current Datalog/fact substrate already has the right shape for
most of these cases: stable identity lives in facts such as resolved uses,
member reads, call arguments, module membership, and assignment/register
relationships. The missing pieces are mostly author-facing vocabulary,
synthesis search, diagnostics, and performance.

## Evidence Snapshot

Gaffer branch `codex/gaffer-p4-reground-20260622` reduced current
`78d928dca7` selector debt from the post-#369 baseline:

- `name_only_total`: 940 -> 905.
- `name_only_fragile`: 939 -> 904.
- Largest remaining buckets: `app/bootstrap` 73, `domains/graph` 39,
  `features/nodes` 32, `domains/ai` 17, plus several 14-17 pin families.

Workers stopped when remaining candidates required neighbor-borrowed context,
long exact bodies, positional multi-declarator pins, or relation shapes that
were visible in the program facts but awkward or unsupported in the selector
surface.

## P0: Inverse Use-Site Selectors

Request: expose a selector form that pins a target by stable use sites rather
than by its own declaration body. This should be a thin language layer over
existing resolved-use/call/member facts where possible.

Needed shapes:

- "the binding passed to this stable callee/member at argument position N";
- "the binding assigned by this setter/callback registration";
- "the binding read by the owner that also reads stable member/key K";
- "the owner whose body calls or registers `@Anchor` with property/member K".

Gaffer evidence:

- `app/bootstrap/checkArrayAtPrototypeSupport` was convertible only because it
  had a distinctive local `Array.prototype.at` body. Similar leaf checks still
  need caller/use-site identity when their own body is empty or generic.
- `app/bootstrap/leafHelpersPendingHome:maxOwnerDisplayCount` is a bare `30`;
  the stable identity is the later owner-path use, not the declaration.
- several bootstrap registry/setter names remain because their stable identity
  is "the slot registered with this API", not a local literal.

Acceptance criteria:

- e2e fixtures for inverse call argument, setter assignment, event/listener
  registration, and use-site-only bare constants;
- fail-closed ambiguity diagnostics that name the competing use sites;
- `synthesize-selectors` candidates prefer these relation forms over neighbor
  body borrowing.

## P0: State Slot / Setter / Getter Families

Request: add a concise way to claim a state cell together with its setter/getter
or to claim one member by its relation to the family.

The language should express patterns like:

- `let state; function setState(v) { state = v; } function getState() { return state; }`
- `let cached; function read() { return cached || (cached = compute()); }`
- singleton and alias pairs such as `const singleton = new C(), exported = singleton`.

Gaffer evidence:

- `app/bootstrap/initBundle:featureFlagClient` and `setFeatureFlagClient` needed
  hand-authored declaration-range `source_match` selectors.
- `cachedOfflineModeState` and workspace-invite singleton/export aliases were
  expressible only as local declaration ranges.
- `nextBlockingVersionDeadlineMs` and `scheduledVersionCheckTimeoutId` were held
  back because the concise candidate was positional in a shared `let` group.

Acceptance criteria:

- surface syntax or synthesis output that names the target slot and relation
  without pinning neighboring declarations positionally;
- diagnostics explaining which family member is ambiguous;
- candidate generation for these forms under `synthesize-selectors`.

## P1: Multi-Declarator Slot Selectors

Request: improve sparse matching for one target inside a multi-declarator
statement, especially when all discriminating evidence lives in sibling
declarators or later uses.

This should avoid selectors whose real identity is "the second variable in a
three-variable declaration." Use stable sibling values only when they identify
the family, then use a named relation to identify the slot.

Gaffer evidence:

- `app/bootstrap/boot_progress/versionCheck` has
  `nextBlockingVersionDeadlineMs`, `scheduledVersionCheckTimeoutId`, and
  `versionConnectivityState`; the safe conversion was only for
  `versionConnectivityListeners`, while the two timer slots stayed name-pinned.
- `app/bootstrap/initBundle:bootGitSha` and `bootEnvName` disambiguate only with
  adjacent bootstrap declarators today.
- meticulous bridge variables were convertible, but only by spelling the shared
  declaration range manually.

Acceptance criteria:

- exact fixtures for single-slot extraction from mixed `let` / `const` runs;
- no neighbor-body pins in generated candidates;
- `selector-debt` reports multi-declarator slots as a distinct blocker class.

## P1: Registry and Roster Selectors

Request: expose stable selectors for common registry/roster shapes where a
binding is identified by membership in a stable registration table or call.

Needed shapes:

- value is included in an array/object passed to `@Registry.register`;
- value is stored under stable key K;
- value participates in a table whose keys or callee are stable, while the
  element binding itself has no local literal.

Gaffer evidence:

- bootstrap system-tool registries, command presets, command lists, and Tana
  paste directive handlers are the next highest-yield `initBundle` groups.
- remaining `features/nodes` candidates included neighbor-registration pins
  that should become registry relation selectors instead.
- graph formula adapters such as `Jd(...)` wrappers are often twins until
  related to their table entry or builtin name.

Acceptance criteria:

- e2e fixtures for object registries, array rosters, and repeated adapter
  wrappers;
- synthesis candidates report the stable key/callee/table that justifies the
  identity;
- ambiguous rosters fail closed with competing keys or call sites.

## P1: Source-Aware Synthesis Performance For Large Prefixes

Request: make prefix-wide candidate discovery practical for large modules such
as `app/bootstrap`.

Gaffer evidence:

- `synthesize-selectors --module-prefix app/bootstrap --candidates 5` was too
  slow for dispatch. Workers had to inspect small item batches manually.
- `app/bootstrap/initBundle` still has 73 fragile pins after the first dispatch,
  so this latency is now a direct workflow bottleneck.

Acceptance criteria:

- warmed prefix inventory under 10 seconds for `app/bootstrap`-scale specs, or
  an explicit offline mode with progress and resumable/cacheable plans;
- item-level filters that reuse prefix analysis rather than restarting full
  source-aware search;
- timing output grouped by blocker class and candidate family.

## P2: Neighbor-Borrow Rejection As A First-Class Diagnostic

Request: teach synthesis and selector-debt reporting to distinguish valid
current-bundle uniqueness from future-stable identity.

Gaffer evidence:

- Workers repeatedly rejected candidates that borrowed unrelated adjacent
  functions/classes or emitted long exact source snapshots.
- `bootGitSha`, `tanaLogger`, copied helpers, and some UI components had unique
  current matches whose uniqueness came from neighboring bodies, not the target.

Acceptance criteria:

- `synthesize-selectors` marks candidate provenance: own literal/member,
  relation anchor, sibling family anchor, or neighbor borrow;
- broad `--apply` refuses neighbor-borrow candidates unless explicitly forced;
- `selector-debt` can rank "needs language relation" separately from "no stable
  evidence found".

## P2: Bootstrap-Specific Worklist Generation

Request: add an inventory mode that emits dispatchable selector-lane worklists
from debt groups: exact item names, likely selector family, candidate command,
and blocker class.

This can be generic, but `app/bootstrap/initBundle` is the stress test.

Acceptance criteria:

- output groups by disjoint write scope and expected selector family;
- each item has one of: landable candidate, needs relation feature, honest
  debt, too expensive;
- the report is stable enough to hand directly to worktree lane agents.

