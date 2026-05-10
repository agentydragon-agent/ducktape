//! Pin the body-index → statement-ordinal conversion when an
//! earlier comma-list var-decl in the chunk shifts the count.
//!
//! `facts::top_level_item_views` splits a top-level
//! `var a = …, b = …;` into two post-split owners with
//! consecutive `StatementOrdinal` values. A subsequent anonymous
//! statement at pre-split body index N therefore lives at
//! post-split statement ordinal N + (number of extra splits in
//! body[..N]).
//!
//! Without the conversion, the Schedule's destination override
//! (which keys off `statement_ordinal`) targets the wrong owner
//! node — the materializer still emits the right body item into
//! the right module, but the realizability check sees a stale
//! module dep graph and the spec gets rejected with a fake
//! cycle. This test is the regression pin: a comma-list before
//! a peeled anon side-effect, with a named member also peeled,
//! and the round-trip must complete without a cycle error.

use debundle_e2e_support::*;

#[test]
fn anon_statement_after_comma_list_resolves_correct_owner() {
    // body[0] = `var a = 1, b = 2;` — 2-decl comma-list (post-split positions 0, 1)
    // body[1] = `console.log("between");`            — anon (post-split position 2)
    // body[2] = `var X = (() => "x")();`             — named (post-split position 3)
    // body[3] = `const Existing = "existing";`       — named (post-split position 4)
    // body[4] = `console.log(Existing);`             — anon (post-split position 5)
    //
    // Pre-split body index of `console.log("between")` is 1.
    // Post-split statement_ordinal is 2 (because body[0]'s
    // comma-list adds +1 to the count).
    //
    // If the conversion is wrong, schedule.rs would override
    // owner with `statement_ordinal == 1` (which is `b`'s owner)
    // instead of the anon owner — `b` would be claimed by
    // x_module while the anon stays in residual, and either:
    //   (a) the module dep graph would have a fake cycle, or
    //   (b) the named-member assertion would catch a non-X
    //       binding in x_module's exports.
    let fixture = run_fixture(FixtureOpts::new(
        r#"var a = 1, b = 2;
console.log("between");
var X = (() => "x")();
const Existing = "existing";
console.log(Existing);
export { a, b, X, Existing };
"#,
        vec![logical_module_with_anon(
            "x_module",
            &[Member::new("X")],
            &[r#"console.log("between");"#],
        )],
    ));

    // x_module owns X and the anon `console.log("between");`.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/x_module.js",
        &[r#"console.log("between")"#, "var X", "export {", "X"],
        // Comma-list var-decls (a, b) must NOT have been swept
        // into x_module by a stale conversion.
        &["var a", "var b", " a = ", " b = "],
    );

    // Residual still emits a, b, Existing, console.log(Existing).
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/residual/unhandled.js",
        &["a", "b", "Existing"],
        &[r#"console.log("between")"#, "var X"],
    );

    // End-to-end: prints "between" then "existing".
    assert_entry_output(&fixture, "between\nexisting\n");
}
