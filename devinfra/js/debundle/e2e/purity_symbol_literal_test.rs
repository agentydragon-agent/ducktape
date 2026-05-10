//! Pin `Symbol(primitive_literal)` purity classification.
//!
//! ECMA-262 §20.4.1.1 says `Symbol(description)`:
//!   1. If NewTarget is not undefined, throw TypeError.
//!   2. If description is undefined, let descString be undefined.
//!   3. Else, let descString be ? ToString(description).
//!   4. Return a new unique Symbol value whose [[Description]]
//!      is descString.
//!
//! For a primitive-literal `description` (string, number,
//! boolean, null, bigint) the `ToString` step runs no user code,
//! so the call has no observable side effects beyond producing a
//! fresh symbol primitive. Same admission contract as the
//! existing `PURE_GLOBAL_CALLS` whitelist (`Boolean`).
//!
//! Without this rule, the classifier returns `Purity::Unknown`
//! for any `Symbol(...)` call, the declarator is flagged
//! `has_side_effect = true`, and the binding gets pulled into the
//! source-order side-effect-order chain. In real chunks that's
//! enough to close phantom multi-module cycles when the spec
//! tries to peel a `Symbol`-bound brand declarator into its own
//! module.

use debundle_e2e_support::*;

#[test]
fn symbol_with_string_literal_arg_classified_pure() {
    // Cycle-forcing fixture: the spec peels `b` (a
    // `Symbol(string-literal)`) into `b_module`. Source-order
    // surrounds `b` with one preceding side-effecting declarator
    // `a` (the IIFE call) so b would inherit a previous-SE
    // s-edge to a if it were classified side-effecting, plus a
    // following declarator `c` whose initializer reads `b` at
    // init so residual has a forward read-dep into b_module.
    //
    // Without this rule: Symbol(...) is Unknown → b is SE →
    // b → a s-edge → cross-module b_module → residual after
    // peel. Combined with residual → b_module (c reads b at
    // init), spec is unrealizable.
    //
    // With this rule: Symbol("b") is Pure → b is not SE → no
    // b → a s-edge. Only edge: residual → b_module. DAG.
    let fixture = run_fixture(FixtureOpts::new(
        r#"const a = (() => 1)();
const b = Symbol("b");
const c = b.description + a;
console.log(c);
export { a, b, c };
"#,
        vec![logical_module("b_module", &[Member::new("b")])],
    ));
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/b_module.js",
        &["const b = Symbol(", "export {", "b"],
        &["const a", "(()=>1)"],
    );
    assert_entry_output(&fixture, "b1\n");
}

#[test]
fn symbol_with_no_args_classified_pure() {
    // No description argument — pure under the same rule
    // (ECMA-262 §20.4.1.1 step 2: descString is undefined when
    // description is undefined, no ToString call).
    let fixture = run_fixture(FixtureOpts::new(
        r#"const a = (() => 1)();
const b = Symbol();
const c = (typeof b) + a;
console.log(c);
export { a, b, c };
"#,
        vec![logical_module("b_module", &[Member::new("b")])],
    ));
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/b_module.js",
        &["const b = Symbol()", "export {", "b"],
        &["const a"],
    );
    assert_entry_output(&fixture, "symbol1\n");
}
