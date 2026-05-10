//! Pin source-order interleaving of anonymous-statement members
//! and named members within the same logical module.
//!
//! Within a module's body, statements emit in their original
//! chunk source order (Invariant #2 in DESIGN.md). Anonymous
//! statements claimed by the module must interleave naturally
//! with named members — there's no separate "anon section" or
//! reordering pass.
//!
//! This guards against a regression where the materializer
//! reorders anon and named owners (e.g. emitting all named
//! members first, then anons at the end). For decorator-style
//! companions like `Ww([Z], $g.prototype, "invites", 2);`, that
//! reordering would put the decorator application BEFORE the
//! class declaration in the emitted module — violating ESM
//! evaluation order and causing
//! `ReferenceError: Cannot access $g before initialization`.

use debundle_e2e_support::*;
use std::fs;

#[test]
fn anon_statements_emit_in_chunk_source_order_alongside_named_members() {
    // Source-order layout interleaves three anon side-effects
    // with two named consts:
    //   1. console.log("before")
    //   2. const A = 1
    //   3. console.log("between")
    //   4. const B = 2
    //   5. console.log("after")
    //   6. const Existing = "existing"          (residual)
    let fixture = run_fixture(FixtureOpts::new(
        r#"console.log("before");
const A = 1;
console.log("between");
const B = 2;
console.log("after");
const Existing = "existing";
export { A, B, Existing };
"#,
        vec![logical_module_with_anon(
            "ab_module",
            &[Member::new("A"), Member::new("B")],
            &[
                r#"console.log("before");"#,
                r#"console.log("between");"#,
                r#"console.log("after");"#,
            ],
        )],
    ));

    // Emitted ab_module body must preserve source order:
    //   console.log("before")  →  const A = 1  →  console.log("between")
    //   →  const B = 2  →  console.log("after")
    //
    // Verified by checking the relative byte offset of each
    // landmark in the read-back source — string-search positions
    // are a stable enough proxy for emission order in this
    // fixture (each substring is unique).
    let ab_src = fs::read_to_string(fixture.out_root.join("static/app/modules/ab_module.js"))
        .expect("read ab_module.js");
    let landmarks = [
        r#"console.log("before")"#,
        "const A = 1",
        r#"console.log("between")"#,
        "const B = 2",
        r#"console.log("after")"#,
    ];
    let positions: Vec<usize> = landmarks
        .iter()
        .map(|needle| {
            ab_src
                .find(needle)
                .unwrap_or_else(|| panic!("ab_module.js missing {needle:?}; got:\n{ab_src}"))
        })
        .collect();
    let mut sorted = positions.clone();
    sorted.sort();
    assert_eq!(
        positions, sorted,
        "ab_module.js statements not in source order: {positions:?} vs sorted {sorted:?}\n{ab_src}",
    );

    // End-to-end behavior: console.log statements run in source
    // order alongside the const initializations.
    assert_entry_output(&fixture, "before\nbetween\nafter\n");
}
