//! Pin OptChain purity classification.
//!
//! `window?.foo?.bar` is observably equivalent to `window.foo.bar`
//! modulo the short-circuit when `window` or `window.foo` is
//! null/undefined. Optional chaining doesn't add semantic side
//! effects of its own; it only short-circuits.
//!
//! Today `purity::classify_expr_purity` returns
//! `Purity::Unknown` for any `Expr::OptChain` regardless of what
//! it expands to, so a `var x = window?.X?.Y;` initializer is
//! classified `has_side_effect = true` even when the underlying
//! chain reads only safe globals. That spurious has_side_effect
//! makes the var participate in the side-effect-order chain, and
//! a peel proposal that would otherwise be a clean
//! Direct-peelable singleton is forced to drag in whatever the
//! immediately-prior side-effecting owner happens to be.
//!
//! On Tana this manifests as the `dg = window?.Meticulous?.…`
//! declarator being chained to the constructor-call declarator
//! `Lge = new $g()` that precedes it in the same comma-list,
//! creating a cross-module side-effect-order edge that closes a
//! 4-module cycle (apply_decorators → tana_logger →
//! test_detection → workspace/invite/state) once the spec
//! claims dg in its proper home.
//!
//! Refinement under test: when `Expr::OptChain` is encountered,
//! recurse through its base (`OptChainBase::Member` /
//! `OptChainBase::Call`) and classify by the underlying access.
//! For static-property reads on a whitelisted receiver (Math,
//! Array, …), this returns `Pure`. The Tana case
//! (`window?.Meticulous?.…`) needs R2 (extending the
//! whitelist to host globals) on top — this test pins R1
//! using a receiver that's already on the whitelist.

use debundle_e2e_support::*;

#[test]
fn optional_chain_on_whitelisted_receiver_classified_pure() {
    // Cycle-forcing fixture:
    //   1. const X = (() => "x")();              — side-effecting (IIFE call); stays in residual
    //   2. const Y = Number?.MAX_SAFE_INTEGER;   — currently OptChain → Unknown → side-effecting; peeled to y_module
    //   3. const Z = Y + 1;                       — reads Y at init; stays in residual
    //   4. console.log(Z);
    //   5. export { X, Y, Z };
    //
    // Today (no R1):
    //   Y has has_side_effect=true (OptChain → Unknown).
    //   S-edges (transitive reduction over SE owners):
    //     Y → X        (Y depends on X via source order, both SE)
    //     console.log(Z) → Y
    //   After peeling Y to y_module, the schedule sees:
    //     y_module → residual (from Y → X s-edge)
    //     residual → y_module (residual reads Y at init via const Z = Y + 1)
    //   That's a cycle in I ∪ S. Validator rejects the spec.
    //
    // After R1:
    //   Y is `Pure` (OptChain recurses into Number.MAX_SAFE_INTEGER
    //   which is whitelisted), so Y has has_side_effect=false.
    //   No Y → X s-edge. Only edge: residual → y_module
    //   (Z's at-init read of Y). DAG. Validator accepts.
    let fixture = run_fixture(FixtureOpts::new(
        r#"const X = (() => "x")();
const Y = Number?.MAX_SAFE_INTEGER;
const Z = Y + 1;
console.log(Z);
export { X, Y, Z };
"#,
        vec![logical_module("y_module", &[Member::new("Y")])],
    ));

    // y_module owns Y but does NOT own X — X stays in residual.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/y_module.js",
        &["const Y = Number?.MAX_SAFE_INTEGER", "export {", "Y"],
        &["const X", "(()=>\"x\")"],
    );
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/residual/unhandled.js",
        &["const X", "const Z"],
        &["const Y"],
    );

    // Behaviour preserved: console.log(Z) prints
    // String(Number.MAX_SAFE_INTEGER + 1).
    assert_entry_output(&fixture, "9007199254740992\n");
}
