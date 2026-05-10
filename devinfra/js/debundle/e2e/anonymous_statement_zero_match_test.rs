//! Pin the zero-match error path for anonymous-statement selectors.
//!
//! When an `anonymous_statements[].match` source doesn't match any
//! top-level statement in the chunk, the materializer must reject
//! the spec with a diagnostic that includes:
//!
//!   1. The logical module's id (so the author knows which entry
//!      is broken).
//!   2. The selector source verbatim (so the author can spot what
//!      changed).
//!   3. A clear "did not match" framing so the author knows the
//!      remediation is "find the new shape" or "remove the entry."
//!
//! Mirrors the validator's "cycle = reject" philosophy: a stale
//! anonymous-statement selector becomes loud at validation time
//! rather than silently skipping the co-move.

use debundle_e2e_support::*;

#[test]
fn rejects_anonymous_statement_match_with_no_top_level_match() {
    let opts = FixtureOpts::new(
        r#"console.log("a");
var X = (() => "x")();
const Existing = "existing";
console.log(Existing);
export { X, Existing };
"#,
        vec![logical_module_with_anon(
            "x_module",
            &[Member::new("X")],
            // Selector that doesn't appear in the chunk: the author's
            // upstream Tana refactor renamed or removed the leading
            // console.log, but the spec still claims it.
            &[r#"console.log("nope");"#],
        )],
    );

    expect_rejection_containing_all(
        opts,
        &[
            // Names the offending logical module so the author
            // knows which spec entry to fix.
            "static/app::x_module",
            // "did not match" framing.
            "did not match",
            // The selector source verbatim so the author can see
            // what's stale.
            r#"console.log("nope")"#,
        ],
    );
}
