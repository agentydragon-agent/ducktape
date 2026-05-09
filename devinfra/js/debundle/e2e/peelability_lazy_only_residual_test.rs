//! Regression-style failing fixture for the
//! `candidate_has_residual_dependency` over-conservativeness
//! at <peelability.rs:730>.
//!
//! Today, that rule marks a peel candidate
//! `BlockedResidualDependency` when ANY outgoing owner edge
//! targets an owner whose destination is residual — including
//! `LazyRead` edges, which DO NOT constrain realizability per
//! <graph.rs> (`EdgeReason::constrains_realizability`). Lazy
//! reads against a residual neighbor are runtime-safe: the
//! function body only fires after both the peeled module and
//! the residual entry have finished evaluating, so there is no
//! top-level cycle and no TDZ.
//!
//! The fixture below is the canonical synthetic shape:
//! `Leaf` is a function whose body lazily reads `Dep`; `Dep`
//! stays in the residual entry. `Leaf`'s only cross-destination
//! owner edge is the lazy read of `Dep`. There is no at-init
//! read, no write, and no side-effect-order edge between them.
//! Singleton-`{Leaf}` is structurally fine to peel — leaving
//! `Dep` in residual is allowed under realizability — yet
//! today the rule blocks the candidate and forces the closure
//! to absorb `Dep` (covered by
//! `owner_graph_report_blocks_residual_entry_dependency_peel_candidate`
//! in `realizability_test.rs`, which pins the current —
//! over-conservative — behavior).
//!
//! Real-world manifestation: Tana's `FocusService` (eF) +
//! `NativeFocusService` (jde) pair, with 17 lazy-only residual
//! neighbors that block the peel even though the realizability
//! cycle would unwind fine. See
//! `gaffer-private/tana/x/modules/compiler/blockers.md`,
//! section "candidate_has_residual_dependency blocks lazy-only
//! edges", for the full diagnosis.
//!
//! Expected behavior (post-fix): the singleton `{Leaf}`
//! candidate is `PeelableNow`, the residual horizon classifies
//! `Leaf` as `Direct`, and `minimal_peel_sets` contains a
//! `SingleOwner` entry for `Leaf` alone. This test asserts
//! that — and consequently fails on current `devel`, where the
//! rule still considers lazy edges.

use analysis::{OwnerGraphReport, PeelCandidateKind, ResidualOwnerPeelStatus};
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
fn singleton_with_lazy_only_residual_edge_should_be_peelable_now() {
    // `Leaf` reads `Dep` only inside a function body — a lazy
    // read. `Dep` stays in residual (no logical_module covers
    // it). `Existing` exists so the chunk has at least one
    // already-extracted module, exercising the residual peel
    // pipeline.
    let mut opts = FixtureOpts::new(
        r#"function Leaf() { return Dep; }
const Dep = "dep";
const Existing = "existing";
console.log(Existing);
export { Leaf, Dep, Existing };
"#,
        vec![logical_module("existing", &[Member::new("Existing")])],
    );
    opts.include_residual = false;
    let fixture = run_fixture(opts);
    assert_entry_output(&fixture, "existing\n");

    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let peelability = &graph.peelability;

    // Post-fix: singleton {Leaf} is `Direct` on the horizon —
    // peeling it alone is safe because the only cross-edge to
    // residual is a lazy read, which doesn't constrain
    // realizability.
    assert!(
        peelability.residual_owner_horizon.iter().any(|owner| {
            owner.members.len() == 1
                && owner.members[0].binding == "Leaf"
                && owner.status == ResidualOwnerPeelStatus::Direct
        }),
        "Leaf should be Direct-peelable (lazy-only edge to residual): {graph:#?}",
    );

    // Post-fix: minimal_peel_sets contains a `SingleOwner`
    // candidate covering `Leaf` alone — no companion needed.
    assert!(
        peelability.minimal_peel_sets.iter().any(|candidate| {
            candidate.owner_set_kind == PeelCandidateKind::SingleOwner
                && candidate.members.len() == 1
                && candidate.members[0].binding == "Leaf"
        }),
        "minimal_peel_sets should include singleton {{Leaf}}: {graph:#?}",
    );
}
