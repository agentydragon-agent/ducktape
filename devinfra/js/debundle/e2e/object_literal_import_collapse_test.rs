//! RED test: pins a lowerer object-literal import-collapse bug.
//!
//! **This test is intentionally failing.** It encodes the divergence
//! between two things that the design says should agree:
//!
//! 1. The peelability gate accepts a spec that moves an object-literal
//!    `const targetConst` (whose initializer reads bindings imported
//!    from another source-chunk module) into its own logical module.
//! 2. The emitted JS for that logical module must remain runtime-loadable
//!    — i.e., every free identifier in the emitted body must resolve to
//!    either a local declaration or a top-level `import` declaration in
//!    the same module.
//!
//! For an object literal `{ keyA: providerExportA, keyB: providerExportB,
//! ... }` whose value identifiers are imports from a sibling module, the
//! current lowerer:
//!
//! 1. Picks up the property keys as if they were the imported
//!    identifiers (i.e. its "what identifiers does this body reference"
//!    pass conflates shorthand key/value with a key-only property name).
//! 2. Naturalizes object-literal shorthand
//!    (<devinfra/js/debundle/logical_modules.rs:3259>
//!    `naturalize_object_literal_shorthand`) so `{ providerExportA:
//!    providerExportA }` collapses to `{ providerExportA }`. With the
//!    collapsed form, the import-planning pass no longer sees the
//!    cross-module identifier reference at all.
//! 3. Does NOT emit `import { providerExportA, providerExportB,
//!    providerExportC } from "../provider_module.js"` in the new
//!    module.
//!
//! Result: cycle gate accepts the spec but the emitted JS references
//! identifiers that don't exist in scope. The module is runtime-broken
//! (Node throws `ReferenceError: providerExportA is not defined` at
//! module-load time).
//!
//! ## Distinction from PR #1625 (`direct_status_overpromise_test.rs`)
//!
//! That earlier RED test pins the **analyzer/proposer** side of a
//! related discrepancy — the analyzer over-claims `Direct` for peels
//! the gate later refuses. This test pins a **lowerer/emitter** bug
//! one step further down the pipeline: the gate accepts the peel but
//! the emitted JS has a missing import. Both bugs were independently
//! observable while peeling Tana's web bundle.
//!
//! ## Production observation
//!
//! Reproduced while peeling Tana's `getActionEventLimits` (an
//! object-literal `const` mapping readable property names to imports
//! from a sibling `sync_timing` module): the resulting standalone
//! module had no `import` directive for the three referenced bindings,
//! and Node refused to load it.
//!
//! ## Suggested fix family
//!
//! Either:
//!
//! 1. The import-planning pass walks object-literal values **before**
//!    shorthand naturalization, so it sees the actual identifier
//!    references and emits imports for cross-module ones.
//! 2. The shorthand naturalizer refuses to collapse a `{ key: value }`
//!    property whose `value` resolves to an imported binding when the
//!    owning module does not declare `value` locally.
//!
//! ## How to flip when the fix lands
//!
//! Once the lowerer emits the missing import, the test becomes GREEN
//! by construction — the assertions then describe correct behavior and
//! the file can drop the "RED pin" framing.
//!
//! ## Under-reproduction note
//!
//! The two-line synthetic source below doesn't repro the full Tana
//! failure shape (no missing import). It does, however, expose a path-
//! normalization smell in exactly the rebase layer the Tana case
//! exercises — the lowerer emits `".././provider_module.js"` instead
//! of the canonical `"../provider_module.js"`. The fix author should
//! re-confirm against the Tana `getActionEventLimits` peel that the
//! full collapse-and-drop chain is also addressed; this fixture pins
//! only the partial (1-of-2) shape that did reproduce in the
//! synthetic harness.

use debundle_e2e_support::*;
use std::fs;

/// Generic-naming chunk source: an entry that imports three minified
/// bindings (`sA`, `sB`, `sC`) from a sibling provider module and
/// builds a `targetConst` object literal whose property values are
/// exactly those imports, but under readable property keys
/// (`propKeyA`, `propKeyB`, `propKeyC`). This is the exact post-minifier
/// shape the bug surfaces on:
///
/// ```js
/// import { sA, sB, sC } from "./provider_module.js";
/// const targetConst = { propKeyA: sA, propKeyB: sB, propKeyC: sC };
/// ```
///
/// The naturalizer wants to rename the value-side scrambled idents
/// (`sA → propKeyA`, etc.) to match the surrounding readable keys, then
/// the shorthand collapse fires. The bug is that the rewriter does this
/// inside the peeled module body without also rewriting (or preserving)
/// the cross-module import that bound those original identifiers.
const CHUNK_SOURCE: &str = r#"import { sA, sB, sC } from "./provider_module.js";
const targetConst = {
  propKeyA: sA,
  propKeyB: sB,
  propKeyC: sC,
};
console.log(targetConst.propKeyA + ":" + targetConst.propKeyB + ":" + targetConst.propKeyC);
export { targetConst };
"#;

const PROVIDER_SOURCE: &str = r#"export const sA = "a";
export const sB = "b";
export const sC = "c";
"#;

/// The peeled `target_module.js` must emit a single
/// `import { sA, sB, sC } from "../provider_module.js"` directive whose
/// path resolves correctly from the moved module's location — otherwise
/// the object-literal initializer references three free variables and
/// Node refuses to load the module.
///
/// RED pin (under-reproduction). The two-line minimal shape doesn't
/// repro the full Tana failure on its own: with the synthetic fixture
/// the lowerer DOES emit the cross-module import. But it emits the
/// import with a malformed relative path (`".././provider_module.js"`,
/// double-dot-slash-dot-slash) that — while Node tolerates it for
/// resolution — is a leading indicator that the rebase logic is fragile
/// in exactly the layer that the Tana case hits. The Tana repro adds
/// (i) naturalization renaming the value-side scrambled idents (`sA →
/// propKeyA`), (ii) the resulting shorthand collapse, and (iii) an
/// import-planning pass that decides the renamed identifiers are
/// "already in scope" because the property key matches. We pin a one-
/// of-two assertion until we can recreate the full chain in the
/// fixture — see PR #1625's analyzer-side companion bug for the
/// proposer/gate side of the same Tana session.
#[test]
fn peeled_object_literal_emits_well_formed_import_for_value_identifiers() {
    let mut opts = FixtureOpts::new(
        CHUNK_SOURCE,
        vec![logical_module(
            "target_module",
            &[Member::new("targetConst")],
        )],
    );
    opts.extra_files = &[("static/app/provider_module.js", PROVIDER_SOURCE)];
    let fixture = run_fixture(opts);

    let target_path = fixture.out_root.join("static/app/modules/target_module.js");
    let target_src =
        fs::read_to_string(&target_path).unwrap_or_else(|e| panic!("read target_module.js: {e}"));

    // The peeled module body still contains the object literal
    // referencing the three imported bindings; the lowerer must have
    // emitted an import directive that brings them into scope.
    assert!(
        target_src.contains("sA") && target_src.contains("sB") && target_src.contains("sC"),
        "target_module.js must still reference all three provider \
         imports in its object literal body; got:\n{target_src}",
    );
    assert!(
        target_src.contains("import") && target_src.contains("provider_module"),
        "target_module.js must import from provider_module when its \
         body references provider exports via object-literal value \
         positions; got:\n{target_src}",
    );

    // RED pin (1 of 2): the rebased import path must be the canonical
    // `../provider_module.js`, not a malformed `.././provider_module.js`
    // form. The double-dot-slash-dot-slash spelling is what the lowerer
    // currently emits — a smell of the same rebase code path the full
    // Tana failure exercises. Flip when the lowerer normalizes its
    // emitted relative paths.
    assert!(
        target_src.contains(r#"from "../provider_module.js""#),
        "RED pin (1 of 2, lowerer-side): target_module.js must emit a \
         normalized relative import path; got:\n{target_src}",
    );

    // RED pin (2 of 2): the emitted module must actually load under
    // Node and produce the chunk's original stdout. `assert_entry_output`
    // surfaces a `ReferenceError` (missing import) or any other module-
    // load failure as a non-zero node exit. If the lowerer's
    // import-emission ever regresses to dropping the cross-module
    // values (per the Tana `getActionEventLimits` discovery), this
    // assertion catches it.
    assert_entry_output(&fixture, "a:b:c\n");
}
