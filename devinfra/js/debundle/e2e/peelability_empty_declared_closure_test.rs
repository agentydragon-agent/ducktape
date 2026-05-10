//! Repro for the empty-declared-closure-overshoot blocker that
//! prevents most blocked owners from getting peel candidates.
//!
//! Empirical observation against the live gaffer Tana graph
//! (May 2026): of 5289 owners on the residual horizon, 4016 are
//! reported `blocked` with empty `peel_set_ids` — i.e., the
//! algorithm couldn't propose any peel candidate, not even a
//! many-owner closure. Tracing one of them (owner:23, binding
//! `TA` / `envConfig`) revealed:
//!
//! - Singleton {TA} is `BlockedResidualDependency` because TA has
//!   a `side_effect_order` edge to owner:7 in residual.
//! - Forward closure of TA's component is 3 owners: TA itself,
//!   plus 2 side-effect-only statements with empty
//!   `declared_bindings`.
//! - `residual_dependency_closure_candidates` rejects the closure
//!   at the representability check (every closure owner must have
//!   a non-empty declared binding to put in `members[]`).
//! - Net effect: TA reports `peel_set_ids: []` even though the
//!   3-owner closure {TA, side_effect_a, side_effect_b} would be
//!   structurally peelable as one module.
//!
//! This minimal fixture reproduces the failure shape: a top-level
//! `var` declaration with a side-effectful initializer, sandwiched
//! between two side-effect-only `console.log` statements. The
//! analyzer emits side-effect-order edges that make the var's
//! singleton candidate `BlockedResidualDependency`. Closure
//! expansion includes the bracketing `console.log` statements,
//! which have empty `declared_bindings`, so the closure is
//! rejected and the var is reported with empty `peel_set_ids`.
//!
//! Expected behavior (post-fix): the algorithm should be able to
//! propose a peel that moves the var together with the side-effect
//! statements as one closure (probably as anonymous statements in
//! the new module), or — alternatively — recognize that the
//! side-effect-order constraint can be satisfied by the eventual
//! ESM import order without co-moving and propose the singleton
//! peel of the var alone. Either way, `peel_set_ids` should be
//! non-empty for the var.

use analysis::{OwnerGraphReport, ResidualOwnerPeelStatus};
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
fn singleton_blocked_only_by_side_effect_order_to_anonymous_owner_should_be_peelable() {
    // Source-order layout:
    //   1. console.log("a")          - side-effect statement, empty declared
    //   2. var X = (() => "x")();    - var_decl with side-effectful initializer
    //                                  → declares X, has_side_effect=True
    //   3. console.log("c")          - side-effect statement, empty declared
    //
    // The analyzer emits side-effect-order edges between the three
    // consecutive side-effect statements. X's singleton candidate
    // is BlockedResidualDependency because of those edges. The
    // closure expansion pulls in the bracketing console.log
    // statements, both empty-declared → closure rejected →
    // peel_set_ids empty.
    let mut opts = FixtureOpts::new(
        r#"console.log("a");
var X = (() => "x")();
const Existing = "existing";
console.log(Existing);
export { X, Existing };
"#,
        vec![logical_module("existing", &[Member::new("Existing")])],
    );
    opts.include_residual = false;
    let fixture = run_fixture(opts);

    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let peelability = &graph.peelability;

    // After the fix, X should NOT be `Blocked` with empty
    // peel_set_ids. It should either be `Direct` (singleton-peel
    // works because the s-edges can be satisfied by ESM load
    // order) or `WithCompanions` (the closure is proposed and
    // includes the side-effect statements as anonymous members).
    let x_horizon = peelability
        .residual_owner_horizon
        .iter()
        .find(|owner| owner.members.iter().any(|m| m.binding == "X"))
        .expect("X should appear on the residual horizon");
    assert!(
        x_horizon.status != ResidualOwnerPeelStatus::Blocked || !x_horizon.peel_set_ids.is_empty(),
        "X should have a peel candidate proposed, not be blocked with empty peel_set_ids: {x_horizon:#?}",
    );
}
