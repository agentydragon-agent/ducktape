//! Pin the ambiguous-match error path for anonymous-statement
//! selectors.
//!
//! Anonymous-statement selectors are unique-by-design: each
//! `match` source must address exactly one top-level statement.
//! When the chunk contains two structurally-identical top-level
//! statements (e.g. two `console.log("dup")` calls) and the
//! selector matches both, the materializer must reject the spec
//! with a diagnostic that includes:
//!
//!   1. The logical module's id.
//!   2. The selector source verbatim.
//!   3. The matching statement ordinals so the author can refine
//!      by writing two distinct selectors (probably with
//!      surrounding context) or accept that the chunk genuinely
//!      contains indistinguishable duplicates.
//!
//! Mirrors the validator's "cycle = reject" philosophy: the
//! resolver never picks one match silently, even if the chunk's
//! source order is well-defined — the spec author has to make
//! the choice explicit.

use debundle_e2e_support::*;

#[test]
fn rejects_anonymous_statement_match_with_multiple_top_level_matches() {
    // Two source-order positions both produce
    // `ExprStmt(Call(console.log, ["dup"]))`. EqIgnoreSpan treats
    // them as equal — there's no way to disambiguate from the
    // selector source alone.
    let opts = FixtureOpts::new(
        r#"console.log("dup");
var X = (() => "x")();
console.log("dup");
const Existing = "existing";
console.log(Existing);
export { X, Existing };
"#,
        vec![logical_module_with_anon(
            "x_module",
            &[Member::new("X")],
            &[r#"console.log("dup");"#],
        )],
    );

    expect_rejection_containing_all(
        opts,
        &[
            // Names the offending logical module.
            "static/app::x_module",
            // "ambiguous" framing.
            "ambiguous",
            // Selector source verbatim.
            r#"console.log("dup")"#,
        ],
    );
}
