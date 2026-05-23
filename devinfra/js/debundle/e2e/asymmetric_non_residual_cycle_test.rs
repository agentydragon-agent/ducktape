//! RED test: the realizability gate must reject asymmetric
//! I-cycles between two non-residual modules — the shape
//! `mod_a ← EagerUse ← mod_b` plus `mod_a → LazyUse → mod_b`.
//!
//! ## Shape
//!
//! Two peeled modules, neither of them residual:
//!
//! - `mod_a` owns a TDZ-locked declaration plus a function whose
//!   body lazily references a binding declared in `mod_b`.
//! - `mod_b` owns a binding whose initializer eager-reads the
//!   declaration in `mod_a` at top level.
//!
//! Owner-graph edges (`(from, to)` = `from` reads `to`):
//!
//! - `mod_b → mod_a` `EagerUse` (constraining)
//! - `mod_a → mod_b` `LazyUse`  (non-constraining)
//!
//! The constraining-edge subgraph is a single arrow, no cycle.
//! The I-graph (constraining ∪ lazy) has a 2-cycle
//! `{mod_a, mod_b}` that does NOT contain `residual`.
//!
//! ## Why the gate accepts today
//!
//! `check_realizability` runs two SCC passes. The second pass
//! (over the full I-graph) only flags an SCC when it both
//! contains the residual module AND has a constraining edge
//! whose TARGET is residual. Asymmetric cycles between two
//! non-residual modules slip past unconditionally — the gate
//! relies on `ChunkFactorization::source_import_position`
//! reversing entry's import list within SCCs so DFS unwinds
//! the dependency first ("Lemma 2").
//!
//! That trick is brittle. It only saves shapes where entry's
//! own import list contains both SCC members AND the
//! materializer's reversal lands the dependent first; the
//! moment a mediator module (whose imports are sorted by
//! `linker_position`, not reversed) reaches into the SCC, DFS
//! enters via the dependency, the lazy back-edge fires the
//! cycle, and the dependent's body evaluates while the
//! dependency's body is still mid-evaluation. Result:
//! `Cannot access 'X' before initialization` at runtime.
//!
//! The asymmetric-non-residual shape is therefore *not*
//! safely realizable in general. The gate must reject any
//! multi-module SCC in I whose internal edges include a
//! constraining edge, regardless of whether residual
//! participates.
//!
//! ## Expected outcomes
//!
//! - **Today (RED)**: gate accepts, materializer emits ESM.
//! - **After the fix**: gate rejects with a cycle report
//!   naming `mod_a` and `mod_b`.

use debundle_e2e_support::*;

#[test]
fn asymmetric_non_residual_i_cycle_is_rejected() {
    // mod_a = {entry_value, lazy_reader}
    //   - entry_value is a TDZ-locked const (target of the
    //     EagerUse back into mod_a).
    //   - lazy_reader's body lazily reads `cross_value` (in
    //     mod_b), creating the non-constraining `mod_a → mod_b`
    //     I-edge that closes the cycle.
    //
    // mod_b = {cross_value}
    //   - cross_value's initializer eager-reads `entry_value`
    //     from mod_a — the constraining `mod_b → mod_a` edge.
    //
    // Residual statements: an at-init `console.log` that
    // exercises both modules at runtime. The export list
    // re-exports every binding so the materializer wires up
    // entry imports for both modules.
    let opts = FixtureOpts::new(
        r#"const entry_value = "alpha";
const cross_value = entry_value + "-beta";
function lazy_reader() { return cross_value; }
console.log(entry_value, cross_value, lazy_reader());
export { entry_value, cross_value, lazy_reader };
"#,
        vec![
            logical_module(
                "mod_a",
                &[Member::new("entry_value"), Member::new("lazy_reader")],
            ),
            logical_module("mod_b", &[Member::new("cross_value")]),
        ],
    );
    expect_rejection(opts, &["cycle", "mod_a", "mod_b"]);
}
