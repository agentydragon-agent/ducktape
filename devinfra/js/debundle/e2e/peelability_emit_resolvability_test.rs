//! E2E fixture for the post-peelability emit-resolvability
//! projection added on top of `peelability.rs`.
//!
//! `materialize_logical_modules` rejects a peel that moves a body
//! whose reads target residual entry binding(s) that aren't on
//! entry's export list — see the bail at
//! "moved module references residual entry binding(s) … not exported
//! by entry". Before this filter, peelability didn't surface that
//! constraint: a candidate could pass cycle/realizability checks and
//! still get rejected when materialization actually ran.
//!
//! The fixture below is the canonical synthetic shape. `Helper` is a
//! `function` whose body lazily reads the residual `Internal` const.
//! `Internal` is NOT in the source's `export {}` set, so peeling
//! `Helper` out of entry would produce a moved module that imports
//! `Internal` from entry — but entry doesn't export it. The
//! `evaluated_owner_sets[]` entry for the singleton {Helper}
//! candidate must therefore have `status ==
//! blocked_emit_resolvability` with `emit_blocked_residual_bindings`
//! listing `Internal`, and `Helper` must NOT appear in
//! `minimal_peel_sets[]`.

use analysis::{OwnerGraphReport, PeelCandidateStatus};
use debundle_e2e_support::*;
use serde::de::DeserializeOwned;
use std::{fs, path::Path};

fn read_json<T: DeserializeOwned>(path: &Path) -> T {
    serde_json::from_str(
        &fs::read_to_string(path)
            .unwrap_or_else(|err| panic!("read JSON report {}: {err}", path.display())),
    )
    .unwrap_or_else(|err| panic!("parse JSON report {}: {err}", path.display()))
}

#[test]
fn unexported_residual_read_marks_candidate_blocked_emit_resolvability() {
    // `Helper` lazy-reads `Internal`, which stays in residual but is
    // not in the source-level `export { … }` list. `Existing` exists
    // so the chunk has at least one already-extracted module — the
    // pipeline expects to do *some* peel work.
    let mut opts = FixtureOpts::new(
        r#"function Helper() { return Internal; }
const Internal = "internal";
const Existing = "existing";
console.log(Existing);
export { Existing };
"#,
        vec![logical_module("existing", &[Member::new("Existing")])],
    );
    opts.include_residual = false;
    let fixture = run_fixture(opts);
    assert_entry_output(&fixture, "existing\n");

    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let peelability = &graph.peelability;

    let helper_candidate = peelability
        .evaluated_owner_sets
        .iter()
        .find(|candidate| candidate.members.len() == 1 && candidate.members[0].binding == "Helper")
        .unwrap_or_else(|| {
            panic!("evaluated_owner_sets should include singleton {{Helper}}: {peelability:#?}")
        });

    assert_eq!(
        helper_candidate.status,
        PeelCandidateStatus::BlockedEmitResolvability,
        "{{Helper}} should be flagged blocked_emit_resolvability \
         (lazy read of unexported residual binding Internal): {peelability:#?}",
    );
    assert_eq!(
        helper_candidate.emit_blocked_residual_bindings,
        vec!["Internal".to_string()],
        "emit_blocked_residual_bindings should pinpoint Internal: {helper_candidate:#?}",
    );

    // The materializer would reject a {Helper} peel — make sure the
    // peelability projection mirrors that by NOT advertising it as a
    // minimal peel set.
    assert!(
        !peelability.minimal_peel_sets.iter().any(|candidate| {
            candidate.members.len() == 1 && candidate.members[0].binding == "Helper"
        }),
        "minimal_peel_sets must omit {{Helper}} when emit-resolvability blocks it: {peelability:#?}",
    );
}
