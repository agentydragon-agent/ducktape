//! End-to-end pinning of the factorize report's correctness against
//! the materializer's actual gates.
//!
//! The closure-based factorizer (`analysis::factorize`) emits a cell
//! per SCC of the residual must-co-locate graph. Each cell carries a
//! verdict from the SSOT `evaluate_peel_candidate` predicate;
//! cells are valid by construction in the emit-resolvability and
//! LazyRebind senses, with cycle/dep blockers reported per cell.
//!
//! Three paired fixtures:
//!
//! 1. **Init-order chain** — a blocked residual cell absorbs its
//!    small at-init prerequisite when the combined closure is
//!    landable.
//! 2. **Single-prereq closure** — a residual binding's body
//!    references another residual binding that isn't on entry's
//!    export list. Promoting the consumer standalone would be
//!    rejected; the factorizer reports the consumer plus its
//!    prerequisite as one landable closure.
//! 3. **Multi-prereq closure** — same shape with two independent
//!    prerequisites, pinning that a blocked consumer can absorb all
//!    small prerequisites at once.
//! 4. **Shared-prereq closure** — two blocked consumers share the
//!    same small prerequisite; the factorizer should merge the
//!    whole closure instead of leaving the prerequisite as a
//!    singleton leaf.

use analysis::OwnerGraphReport;
use debundle_e2e_support::*;
use peel_factorize::factorize;
use serde::de::DeserializeOwned;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

fn read_json<T: DeserializeOwned>(path: &Path) -> T {
    serde_json::from_str(
        &fs::read_to_string(path)
            .unwrap_or_else(|err| panic!("read JSON report {}: {err}", path.display())),
    )
    .unwrap_or_else(|err| panic!("parse JSON report {}: {err}", path.display()))
}

#[test]
fn factorizer_orders_chain_cells_by_dependency_and_materializer_accepts_promotion() {
    // Source: three `const` initializers chained by at-init reads
    // (b reads a, c reads b). Only `a` is logical-module-claimed;
    // {b, c} sit residual.
    //
    // The closure-based analyzer treats `c → b` as a dependency
    // (c needs b first). The CLI factorizer should surface the
    // useful peel shape directly: {b, c}, since b is small and the
    // combined closure is landable.
    let chunk_source = r#"const a = 1;
const b = a + 1;
const c = b + 2;
export { a, b, c };
"#;

    let mut opts = FixtureOpts::new(
        chunk_source,
        vec![logical_module("anchors/a", &[Member::new("a")])],
    );
    opts.unassigned_mode = unassigned_mode_inline();
    let fixture = run_fixture(opts);
    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let report = factorize(&graph, &BTreeMap::new(), &BTreeMap::new(), 2000);

    let chain_cell = report
        .proposals
        .iter()
        .find(|p| {
            p.binding_ids.contains(&"b".to_string()) && p.binding_ids.contains(&"c".to_string())
        })
        .expect("factorizer should propose a combined cell for `b` and `c`");
    assert!(
        chain_cell.landable_today,
        "combined chain closure must be landable; got cell={chain_cell:?}",
    );

    // The materializer accepts the lane-worker decision to promote
    // both into one combined module, matching the proposal.
    let promoted_opts = FixtureOpts::new(
        chunk_source,
        vec![
            logical_module("anchors/a", &[Member::new("a")]),
            logical_module("helpers/chain", &[Member::new("b"), Member::new("c")]),
        ],
    );
    let _ = run_fixture(promoted_opts);
}

#[test]
fn factorizer_combines_emit_blocked_cell_with_blocker_binding() {
    // `dep` is residual and NOT in entry's `export { ... }` list.
    // `consumer` lazily reads `dep` (inside its body). Promoting
    // consumer's analyzer cell alone would be rejected, but
    // promoting {dep, consumer} together is valid and small enough
    // to propose directly.
    //
    // `anchor` exists so the chunk has at least one active logical
    // module (the spec rejects all-residual chunks); `dep` and
    // `consumer` stay in the residual entry via
    // `unassigned_mode_inline()` (`InlineInEntry`).
    let chunk_source = r#"const anchor = "anchor";
const dep = "secret";
function consumer() { return dep; }
export { anchor, consumer };
"#;

    let mut opts = FixtureOpts::new(
        chunk_source,
        vec![logical_module("anchors/anchor", &[Member::new("anchor")])],
    );
    opts.unassigned_mode = unassigned_mode_inline();
    let fixture = run_fixture(opts);
    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let report = factorize(&graph, &BTreeMap::new(), &BTreeMap::new(), 2000);

    let combined = report
        .proposals
        .iter()
        .find(|p| {
            p.binding_ids.contains(&"dep".to_string())
                && p.binding_ids.contains(&"consumer".to_string())
        })
        .expect("factorizer should combine `consumer` with `dep`");
    assert!(
        combined.landable_today,
        "combined prerequisite closure must be landable; got {combined:?}",
    );
    assert!(
        combined.emit_blocked_residual_bindings.is_empty(),
        "internalized blocker should be cleared; got {:?}",
        combined.emit_blocked_residual_bindings,
    );
}

#[test]
fn factorizer_combines_blocked_consumer_with_all_landable_prerequisites_when_under_cap() {
    // `dep_a` and `dep_b` are independently landable leaves. `consumer`
    // reads both, so promoting `consumer` alone would fail
    // emit-resolvability. The useful proposal is the whole closure:
    // {dep_a, dep_b, consumer}. This pins the factorizer behavior we
    // want for Tana deferred queues: do not force lane workers to
    // discover and hand-assemble every blocked cell's prerequisite
    // closure when the closure itself is small enough to review.
    let chunk_source = r#"const anchor = "anchor";
const dep_a = "left";
const dep_b = "right";
function consumer() { return dep_a + dep_b; }
export { anchor, consumer };
"#;

    let mut opts = FixtureOpts::new(
        chunk_source,
        vec![logical_module("anchors/anchor", &[Member::new("anchor")])],
    );
    opts.unassigned_mode = unassigned_mode_inline();
    let fixture = run_fixture(opts);
    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let report = factorize(&graph, &BTreeMap::new(), &BTreeMap::new(), 2000);

    let combined = report
        .proposals
        .iter()
        .find(|p| {
            p.binding_ids.contains(&"dep_a".to_string())
                && p.binding_ids.contains(&"dep_b".to_string())
                && p.binding_ids.contains(&"consumer".to_string())
        })
        .expect("factorizer should combine the consumer with both prerequisites");
    assert!(
        combined.landable_today,
        "combined prerequisite closure must be landable; got {combined:?}",
    );

    // The materializer already accepts the same closure when authored
    // by hand, proving this is a planner limitation rather than a
    // lowerer/materializer limitation.
    let promoted_opts = FixtureOpts::new(
        chunk_source,
        vec![
            logical_module("anchors/anchor", &[Member::new("anchor")]),
            logical_module(
                "helpers/consumer_closure",
                &[
                    Member::new("dep_a"),
                    Member::new("dep_b"),
                    Member::new("consumer"),
                ],
            ),
        ],
    );
    let _ = run_fixture(promoted_opts);
}

#[test]
fn factorizer_combines_multiple_consumers_with_shared_prerequisite_when_under_cap() {
    // `shared` is a small residual prerequisite used by two residual
    // consumers. Promoting either consumer alone would leave a
    // residual dependency, and promoting only {shared, consumer_a}
    // would still leave consumer_b blocked. The useful factor is the
    // full shared-prerequisite closure.
    let chunk_source = r#"const anchor = "anchor";
const shared = "shared";
const consumer_a = shared + "/a";
const consumer_b = shared + "/b";
export { anchor, consumer_a, consumer_b };
"#;

    let mut opts = FixtureOpts::new(
        chunk_source,
        vec![logical_module("anchors/anchor", &[Member::new("anchor")])],
    );
    opts.unassigned_mode = unassigned_mode_inline();
    let fixture = run_fixture(opts);
    let graph: OwnerGraphReport =
        read_json(&fixture.report_root.join("static/app/owner_graph.json"));
    let report = factorize(&graph, &BTreeMap::new(), &BTreeMap::new(), 2000);

    let combined = report
        .proposals
        .iter()
        .find(|p| {
            p.binding_ids.contains(&"shared".to_string())
                && p.binding_ids.contains(&"consumer_a".to_string())
                && p.binding_ids.contains(&"consumer_b".to_string())
        })
        .expect("factorizer should combine both consumers with their shared prerequisite");
    assert!(
        combined.landable_today,
        "combined shared-prerequisite closure must be landable; got {combined:?}",
    );

    let promoted_opts = FixtureOpts::new(
        chunk_source,
        vec![
            logical_module("anchors/anchor", &[Member::new("anchor")]),
            logical_module(
                "helpers/shared_consumer_closure",
                &[
                    Member::new("shared"),
                    Member::new("consumer_a"),
                    Member::new("consumer_b"),
                ],
            ),
        ],
    );
    let _ = run_fixture(promoted_opts);
}
