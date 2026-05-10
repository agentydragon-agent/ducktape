//! Pin `purity: pure` propagation from chunk_renames members
//! into `declared_pure`.
//!
//! `Member.purity` is collected only from logical-module
//! members today. `chunk_renames.members[].purity` and
//! `residual_modules.members[].purity` are silently dropped.
//! That forces the spec author to either peel the binding into
//! a 1-member logical module just to get the purity hint
//! propagated, or leave the call classified `Unknown`.
//!
//! Refinement: chunk_renames + residual_modules members with
//! `purity: pure` contribute to `declared_pure` alongside
//! logical-module members. One spec entry per imported function
//! carries both the rename (via the existing chunk_renames
//! pipeline) and the purity hint.
//!
//! In-residual rename behavior is already pinned by
//! `chunk_renames_test`; this test focuses on the purity-side
//! propagation.

use debundle_e2e_support::*;
use serde_json::json;

#[test]
fn chunk_rename_with_purity_pure_propagates_to_call_classifier() {
    // Fixture:
    //   - vendor.js exports a function `f`.
    //   - entry imports `f as cx`.
    //   - `const a = (() => 1)();`  — SE, stays in residual
    //   - `const b = cx();`          — would be SE without the rule
    //                                  (imported, not in declared_pure)
    //   - `const c = a + b;`         — reads b at init
    //   - peel target: b → b_module
    //
    // Without the rule:
    //   cx() is Unknown → b is SE → b → a s-edge across
    //   b_module → residual. Combined with residual → b_module
    //   (c's at-init read of b), cycle.
    //
    // With the rule:
    //   chunk_renames carries `purity: pure` for cx → cx in
    //   declared_pure → cx() is Pure → b is Pure → no S-chain
    //   participation. Only edge: residual → b_module. DAG.
    let opts = FixtureOpts {
        source: r#"import { f as cx } from "./vendor.js";
const a = (() => 1)();
const b = cx();
const c = a + b;
console.log(c);
export { a, b, c };
"#,
        logical_modules: vec![logical_module("b_module", &[Member::new("b")])],
        residual: None,
        chunk_renames: Some(json!({
            "id": "chunk_renames__static_app",
            "members": [
                {
                    "name": "getMobxGlobalState",
                    "selector": {
                        "binding": {
                            "name": "cx",
                            "kind": "import_specifier",
                        },
                    },
                    "purity": "pure",
                },
            ],
        })),
        chunk_id: "static/app",
        include_residual: true,
        extra_files: &[(
            "static/app/vendor.js",
            "export function f() { return 1; }\n",
        )],
    };
    let fixture = run_fixture(opts);

    // The peel succeeded: b is in b_module without dragging a.
    // The fact that the build didn't error on a cycle proves
    // that `cx()` was classified Pure by the call classifier.
    assert_module_source(
        &fixture.out_root,
        "static/app/modules/b_module.js",
        &["const b = "],
        &["const a", "(()=>1)"],
    );

    // Behaviour preserved: c == a + b == 1 + 1 == 2.
    assert_entry_output(&fixture, "2\n");
}
