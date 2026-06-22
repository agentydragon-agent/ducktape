# Selector Resolver — Execution Runbook to the Endpoint

Companion to the design narrative <selector_constraint_model.md> and the debt
worklist <../debug/2026_06_19_p4_debt_worklist.md>. This file is the **execution
contract**: the ordered phases, the gates that authorize each irreversible step,
the abort bar, and the decisions pre-made so execution does not stall.

## Endpoint (definition of done)

Selector resolution is one whole-spec/component constraint solve over source
facts. Every selector form (`source_match`, binding groups, anonymous
statements, and relational selectors) lowers to one selector IR; `@Name` is a
shared solver variable, not a lookup into already-resolved members; no-match,
ambiguous, and duplicate-claim diagnostics are projections of the solver result
(`target` categoricity + `all_different`); and `materialize` consumes the
resolved claim map before the existing atomic/realizability gates run.

Driving downstream name-pin debt to zero is now dogfood for this endpoint, not
the endpoint itself. Real-spec conversions should expose missing facts,
authoring vocabulary, synthesis defaults, or diagnostics that the global solver
needs. **Invariant (non-negotiable): fail-closed** — a selector that cannot
resolve categorically errors, never guesses; no special-case hacks, no silent
fallbacks.

## Next

Execute the global-solve cutover in dependency order:

1. Define the selector IR and fact schema shared by `run`, `validate`,
   `match-selector`, `selector-debt`, and synthesis.
2. Lower today's `source_match` / binding-group language into that IR and prove
   parity against the fact-based `ChunkResolver`.
3. Carry spec target symbols through the solve so `@Name` is a shared variable
   and mutually-constraining selector clusters do not need anchor-first order.
4. Implement solver result projection: per-target no-match / ambiguous /
   unique, plus `all_different` duplicate-claim diagnostics.
5. Integrate the result into `materialize` as a resolved claim map, then fold
   the existing relational bridge passes into derived predicates.
6. Use Gaffer selector-stabilization lanes to collect missing language/fact
   requirements and to prove byte-identical real-spec output, not to keep
   expanding the staged resolver architecture.

## Execution Notes

Real-spec conversions land in gaffer-private only after the Ducktape-side change
they exercise exists, or when the conversion documents a missing Ducktape
language/fact/diagnostic requirement. Use that repo's current `tana/re` agent
instructions for branch, commit, and source-debundler override details; do not
freeze one session's degraded-web command line here. The durable lane recipe
from the 2026-06 run remains in
<../debug/2026_06_20_gaffer_phaseA_lane_recipe.md>.

Each conversion step should still end in a verified commit: changed lib and
consumer tests green, lint on, and generated output byte-identical unless the
step explicitly changes output. For resolver-architecture steps, add the
smallest synthetic fixture that proves the new IR/fact/diagnostic behavior, then
dogfood on Gaffer only when the public fixture is green.

## Verification gates

- **Build/test gate**: build the changed lib **and its consumers** (proves match
  exhaustiveness); run the changed area's tests `--cache_test_results=no`, lint on (no
  `--config=nolint` on a step's final run).
- **Resolver parity gate**: while both resolver paths exist, the global solve and
  current fact-based/staged resolver agree on every resolved target, no-match,
  ambiguous match, duplicate claim, and unsupported construct covered by the
  differential corpus.
- **Conversion gate (Gaffer)**: after converting a real selector from a name-pin
  to a structural or relational selector, the spec's debundle **generated output
  is byte-identical** and the converted selector resolves to the **same binding**
  the name-pin did. Cross-ref-only selectors have no hand-rolled twin, so prove
  them through solver categoricity and byte-identical output.

## Abort & escalation bar (the goal's central directive)

- If a selector kind or the relational model **will not admit one general faithful
  encoding** — without a special-case hack or a silent fallback — **STOP**. Write the
  dead-end analysis into a `debug/` note (what was attempted, why it fails, what the
  model would need), commit it, and check in with the user. **Do not hack toward the
  endpoint.** An honest dead end beats a resolver we can't trust.
- **Check in (do not self-resolve)** on: a genuine design fork with no principled
  default; a parity regression whose faithful fix isn't clear; a faithful-encoding
  dead end. Everything else: proceed on best engineering judgment.
- Fail-closed is non-negotiable: a selector that cannot be resolved categorically must
  **error**, never guess.

## Pre-made decisions (so execution does not stall)

- **`@Name` model**: in the endpoint, `@Name` is a shared solver variable for the
  named target. The production anchor-first map is only the current bridge
  around missing global solve plumbing; do not add new architecture that depends
  on anchor-first ordering.
- **`Resolution` in-pipeline**: `selector_solve::solve` consumes the lean
  `OwnerGraph`; in-pipeline, project the in-memory `analysis::OwnerGraph` into
  the lean struct — **do not** couple `selector_solve` to the `analysis` crate's
  rich types until the global fact store replaces the bridge.

## Remaining phases

The old X1-X3/X4/X5 naming described the migration as "add relation primitives,
then count, then solve globally." The new framing collapses that into one P0
path:

### Phase G1 — IR and fact-store contract

Specify target variables, local variables, shape atoms, relation atoms, derived
predicates, source spans, and diagnostics in one engine-facing model.

### Phase G2 — `source_match` parity lowering

Compile current JS-with-holes selectors into the IR and prove equivalence with
the fact-based `ChunkResolver`.

### Phase G3 — shared-variable solve

Solve selector components with shared `@Name` variables and per-target
categoricity. Add `all_different` as part of the result contract.

### Phase G4 — materializer cutover

Replace the staged claim construction with a solver-produced claim map. The
owner graph, atomic-DAG, module-DAG, and emit gates consume the same resolved
ownership they do today.

### Phase G5 — relation/language fold-in

Fold `cross_ref`, `reads_member`, `member_of_module`, `passed_to_call`,
`makes_decorate_call`, `intrinsic_alias`, and the Gaffer feature-request
vocabulary into IR atoms or derived predicates. Delete the late bridge passes
only after parity and real-spec byte identity are proven.
