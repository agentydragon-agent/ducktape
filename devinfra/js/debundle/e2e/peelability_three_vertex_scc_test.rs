//! Regression fixture for N-owner SCC recovery via the
//! residual-dependency-closure path in `peelability.rs`.
//!
//! Earlier analysis claimed the algorithm only handled 2-owner pair
//! peels for cyclic blockers (see
//! `gaffer-private/tana/x/research/hub_class_peel_blockers.md`).
//! That was wrong: `residual_dependency_closure_candidates` runs
//! Tarjan-SCC over the residual subgraph and proposes the SCC's
//! closure as a multi-owner peel, including for 3+ vertex cases.
//!
//! This test pins the working behavior so future refactors don't
//! regress it: a 3-vertex at-init read cycle is correctly proposed
//! as a 3-owner peel candidate.
//!
//! Fixture: three top-level vars A, B, C such that
//!     var A = B   (A reads B at-init)
//!     var B = C   (B reads C at-init)
//!     var C = A   (C reads A at-init)
//! `var` hoisting avoids TDZ; the assignments resolve to `undefined`
//! at runtime. The SCC is structurally clean (no out-edges to
//! residual side-effect statements that would force the closure to
//! grow), so the proposed peel is exactly {A, B, C}.

use analysis::{OwnerGraphReport, ResidualOwnerPeelStatus};
use debundle_e2e_support::*;
use serde::de::DeserializeOwned;
use std::{collections::BTreeSet, fs, path::Path};

fn read_json<T: DeserializeOwned>(path: &Path) -> T {
    serde_json::from_str(
        &fs::read_to_string(path)
            .unwrap_or_else(|err| panic!("read JSON report {}: {err}", path.display())),
    )
    .unwrap_or_else(|err| panic!("parse JSON report {}: {err}", path.display()))
}

#[test]
fn three_vertex_constraining_scc_should_be_peelable_as_one_owner_closure() {
    // Three vars forming a 3-vertex at-init read cycle:
    //   A reads B   (var A = B)
    //   B reads C   (var B = C)
    //   C reads A   (var C = A)
    // `var` hoisting avoids TDZ; assignments run in order with
    // the still-uninitialized targets resolving to `undefined`,
    // so the bundle runs without crashing.
    //
    // The SCC has no out-edges to residual (no helper called
    // from inside, no console.log reading A/B/C from residual),
    // so the closure for the SCC is exactly {A, B, C}. The
    // algorithm correctly proposes this as a 3-owner peel
    // candidate in `minimal_peel_sets`.
    //
    // `Existing` is an already-extracted module so the residual
    // peel pipeline has work to do. `include_residual = false`
    // keeps the pipeline strict about what the chunk emits.
    let mut opts = FixtureOpts::new(
        r#"var A = B;
var B = C;
var C = A;
const Existing = "existing";
console.log(Existing);
export { A, B, C, Existing };
"#,
        vec![logical_module("existing", &[Member::new("Existing")])],
    );
    opts.include_residual = false;
    let fixture = run_fixture(opts);

    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let peelability = &graph.peelability;

    // `minimal_peel_sets` contains an owner closure of size 3
    // covering exactly {A, B, C}: the whole constraining SCC is
    // proposed as one peel module by the closure path.
    let three_owner_scc_closures: Vec<_> = peelability
        .minimal_peel_sets
        .iter()
        .filter(|candidate| {
            let names: BTreeSet<_> = candidate
                .members
                .iter()
                .map(|m| m.binding.as_str())
                .collect();
            names == BTreeSet::from(["A", "B", "C"]) && candidate.owner_ids.len() == 3
        })
        .collect();
    assert!(
        !three_owner_scc_closures.is_empty(),
        "minimal_peel_sets should include the 3-owner SCC {{A, B, C}}: {graph:#?}",
    );

    // Each of A, B, C is on the residual horizon with a non-empty
    // `peel_set_ids` (status `WithCompanions`) referencing the
    // 3-owner closure.
    for binding in ["A", "B", "C"] {
        assert!(
            peelability.residual_owner_horizon.iter().any(|owner| {
                owner.members.len() == 1
                    && owner.members[0].binding == binding
                    && owner.status == ResidualOwnerPeelStatus::WithCompanions
                    && !owner.peel_set_ids.is_empty()
            }),
            "{binding} should be WithCompanions with non-empty peel_set_ids: {graph:#?}",
        );
    }
}
