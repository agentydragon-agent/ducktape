//! Round-trip pin for anonymous-statement member support.
//!
//! Today the spec only addresses named bindings via
//! `members[].selector.binding.name`. Anonymous side-effect
//! statements (top-level `console.log(...)`, IIFE preludes,
//! decorator-application calls like `applyDecorators(C.prototype, …)`)
//! have empty `declared_bindings` and no name to reference, so the
//! materializer can't emit them as part of any logical module —
//! it silently leaves them in residual.
//!
//! That blocks 4015 of 4106 named horizon bindings in Tana from
//! peeling: their only peel proposal is a closure where the
//! companions are anonymous statements (decorator applications on
//! the class prototype, runtime init calls, bundle preludes). See
//! `peelability_empty_declared_closure_test` for the analysis-side
//! pin; this test pins the materialization-side fix.
//!
//! Spec extension under test: a sibling field on
//! `spec::LogicalModule`:
//!
//! ```yaml
//! x_module:
//!   members:
//!     - selector: { binding: { name: X } }
//!   anonymous_statements:
//!     - match: 'console.log("a");'
//! ```
//!
//! `match` carries the JS source of the target statement verbatim;
//! the resolver parses it as a single `Stmt` and walks the chunk's
//! top-level statements looking for exactly one whose AST matches
//! (modulo spans). Resolved owners flow into the same
//! `selected_ordinals` set the materializer already builds for
//! named members.
//!
//! Per the user constraint, the selector must address statements
//! by **AST shape**, not line/column — the Tana dump is prettified
//! and lines aren't stable across re-prettifies.

use debundle_e2e_support::*;

#[test]
fn round_trip_peels_anon_statement_with_named_member() {
    // Source-order layout:
    //   1. console.log("a")        - anon side-effect (empty declared)
    //   2. var X = (() => "x")()   - var_decl with side-effectful IIFE init
    //   3. const Existing          - named const, stays in residual
    //   4. console.log(Existing)   - anon side-effect, stays in residual
    //
    // The s-edge from owner(X) to owner(console.log("a")) makes the
    // singleton {X} `BlockedResidualDependency`. The proposed peel
    // is the closure {console.log("a"), X}, which the materializer
    // can only emit if the spec carries an anon-statement entry
    // pointing at the leading console.log.
    let fixture = run_fixture(FixtureOpts::new(
        r#"console.log("a");
var X = (() => "x")();
const Existing = "existing";
console.log(Existing);
export { X, Existing };
"#,
        vec![logical_module_with_anon(
            "x_module",
            &[Member::new("X")],
            &[r#"console.log("a");"#],
        )],
    ));

    // End-to-end behavior: console.log("a") then console.log(Existing).
    // x_module body runs first via ESM import order; residual second.
    assert_entry_output(&fixture, "a\nexisting\n");

    // The peeled module must carry both the leading console.log
    // and the var X declaration, in source order, plus an
    // `export { X }` re-export so entry's `import { X } from "./..."`
    // resolves.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/x_module.js",
        &[r#"console.log("a")"#, "var X", "export {", "X"],
        &[],
    );

    // The leading console.log and X's declaration must be gone
    // from residual (otherwise the side-effect runs twice).
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/residual/unhandled.js",
        &[],
        &[r#"console.log("a")"#, "var X"],
    );
}
