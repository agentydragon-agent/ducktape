//! Integration tests for the `peel::quotient` kernel and the
//! `factorize` renderer-over-quotient. Compiled against `:peel`'s
//! public API as a separate crate; bypasses the broken `:peel_test`
//! target.
//!
//! Test list (commit 1 + 1b of `plans/peel_proposer_contraction_model.md`):
//!
//! - `seed_pre_contracts_atomic_units`
//! - `seed_pre_contracts_spec_modules`
//! - `seed_skips_unrealizable_spec_module_contraction_and_reports`
//! - `seed_atomic_unit_contractions_never_rejected_on_well_formed_input`
//! - `seed_rejection_diagnostic_is_canonical`
//! - `contract_never_un_contracts`
//! - `factorize_golden_output_unchanged` — load-bearing snapshot
//!   assertion that the renderer-over-quotient produces byte-identical
//!   output to the pre-commit-1 binary.
//! - `partition_constructor_contracts_each_group` — internal
//!   invariant of commit 1b: the partition-based kernel constructor
//!   collapses each input group into one class, regardless of
//!   pre-existing edges between the owners.

use std::collections::BTreeMap;

use analysis::{
    AtomicGraphReport, AtomicUnitEdgeReport, AtomicUnitReport, BindingReport, DepKind, LineRange,
    ModuleReportRef, OwnerGraphEdgeReport, OwnerGraphNodeReport, OwnerGraphQuotientReport,
    OwnerGraphReport, Purity, SourceLocation, StatementKind, StatementOrdinal,
};

use peel::factorize::factorize;
use peel::quotient::{
    OwnerIdx, QuotientGraph, SeedContractionRejected, SpecModuleGroup, build_seed_quotient,
};

// ---------- Fixture helpers (generic; no Tana/gaffer strings). ----------

fn binding(name: &str) -> BindingReport {
    BindingReport {
        binding: name.into(),
        export_name: name.into(),
    }
}

fn module_ref(id: &str, residual: bool) -> ModuleReportRef {
    ModuleReportRef {
        id: id.to_string(),
        label: id.to_string(),
        residual,
        index: None,
        target_file: (!residual).then(|| id.to_string()),
    }
}

fn owner(
    id: &str,
    ordinal: usize,
    bindings: &[&str],
    lines: usize,
    destination: ModuleReportRef,
) -> OwnerGraphNodeReport {
    OwnerGraphNodeReport {
        id: id.to_string(),
        statement_ordinal: StatementOrdinal(ordinal),
        source_location: Some(SourceLocation {
            source_path: "x.js".to_string(),
            start_line: ordinal * 100,
            end_line: ordinal * 100 + lines.saturating_sub(1),
        }),
        declared_bindings: bindings.iter().map(|b| binding(b)).collect(),
        statement_kind: StatementKind::VarDecl,
        purity: Purity::Pure,
        destination,
    }
}

fn residual_owner(
    id: &str,
    ordinal: usize,
    bindings: &[&str],
    lines: usize,
) -> OwnerGraphNodeReport {
    owner(
        id,
        ordinal,
        bindings,
        lines,
        module_ref("logical:residual", true),
    )
}

fn active_owner(
    id: &str,
    ordinal: usize,
    bindings: &[&str],
    lines: usize,
    module_path: &str,
) -> OwnerGraphNodeReport {
    owner(id, ordinal, bindings, lines, module_ref(module_path, false))
}

fn owner_edge(
    id: &str,
    source: &str,
    target: &str,
    kind: DepKind,
    constrains: bool,
) -> OwnerGraphEdgeReport {
    OwnerGraphEdgeReport {
        id: id.to_string(),
        source: source.to_string(),
        target: target.to_string(),
        edge_kind: kind,
        binding: None,
        statement_ordinal: StatementOrdinal(0),
        constrains_init_order: constrains,
    }
}

fn atomic_unit_for(id: &str, owners: &[&OwnerGraphNodeReport]) -> AtomicUnitReport {
    let mut owner_ids = Vec::new();
    let mut members = Vec::new();
    let mut destinations = BTreeMap::<String, ModuleReportRef>::new();
    let mut line_range = LineRange::new();
    let mut min_ordinal = usize::MAX;
    let mut max_ordinal = 0usize;
    for o in owners {
        owner_ids.push(o.id.clone());
        members.extend(o.declared_bindings.clone());
        destinations.insert(o.destination.id.clone(), o.destination.clone());
        if let Some(location) = &o.source_location {
            line_range.expand(location);
        }
        min_ordinal = min_ordinal.min(o.statement_ordinal.0);
        max_ordinal = max_ordinal.max(o.statement_ordinal.0);
    }
    AtomicUnitReport {
        id: id.to_string(),
        owner_ids,
        members,
        anonymous_statement_owner_ids: Vec::new(),
        destinations: destinations.into_values().collect(),
        causes: Vec::new(),
        size_lines_estimate: line_range.size_estimate(),
        source_line_range: line_range.into_array(),
        ordinal_span: max_ordinal.saturating_sub(min_ordinal),
    }
}

fn atomic_edge(id: &str, source: &str, target: &str) -> AtomicUnitEdgeReport {
    AtomicUnitEdgeReport {
        id: id.to_string(),
        source: source.to_string(),
        target: target.to_string(),
        edge_kinds: vec![DepKind::EagerUse],
        owner_edge_ids: vec![id.replace("atomic", "edge")],
        constrains_init_order: true,
    }
}

fn graph_of(
    nodes: Vec<OwnerGraphNodeReport>,
    edges: Vec<OwnerGraphEdgeReport>,
    units: Vec<AtomicUnitReport>,
    unit_edges: Vec<AtomicUnitEdgeReport>,
) -> OwnerGraphReport {
    OwnerGraphReport {
        chunk_id: "x".to_string(),
        nodes,
        edges,
        quotient: OwnerGraphQuotientReport {
            nodes: vec![],
            edges: vec![],
            sccs: vec![],
        },
        atomic_graph: AtomicGraphReport {
            nodes: units,
            edges: unit_edges,
        },
    }
}

// ---------- Tests. ----------

#[test]
fn seed_pre_contracts_atomic_units() {
    // Fixture: a 3-binding atomic unit. After seeding, all three
    // owners must share a class.
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    let c = residual_owner("owner:c", 3, &["BindingC"], 5);
    let unit = atomic_unit_for("atomic:0", &[&a, &b, &c]);
    let report = graph_of(
        vec![a.clone(), b.clone(), c.clone()],
        vec![],
        vec![unit.clone()],
        vec![],
    );
    let (q, rejected) = build_seed_quotient(&report, &report.atomic_graph.nodes, &[], 10_000);
    assert!(
        rejected.is_empty(),
        "well-formed atomic unit must not produce rejections: {rejected:?}",
    );
    let a_idx = q.owner_idx_of("owner:a").expect("a in graph");
    let b_idx = q.owner_idx_of("owner:b").expect("b in graph");
    let c_idx = q.owner_idx_of("owner:c").expect("c in graph");
    assert_eq!(q.class_of(a_idx), q.class_of(b_idx));
    assert_eq!(q.class_of(b_idx), q.class_of(c_idx));
}

#[test]
fn seed_pre_contracts_spec_modules() {
    // Fixture: spec module declares two owners. After seeding, they
    // must share a class.
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    let report = graph_of(
        vec![a.clone(), b.clone()],
        vec![],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&b]),
        ],
        vec![],
    );
    let spec = vec![SpecModuleGroup {
        module_id: "mod_alpha".to_string(),
        owner_ids: vec!["owner:a".to_string(), "owner:b".to_string()],
    }];
    let (q, rejected) = build_seed_quotient(&report, &report.atomic_graph.nodes, &spec, 10_000);
    assert!(
        rejected.is_empty(),
        "well-formed spec module must not produce rejections: {rejected:?}",
    );
    let a_idx = q.owner_idx_of("owner:a").unwrap();
    let b_idx = q.owner_idx_of("owner:b").unwrap();
    assert_eq!(q.class_of(a_idx), q.class_of(b_idx));
}

#[test]
fn seed_skips_unrealizable_spec_module_contraction_and_reports() {
    // Fixture: spec declares two modules mod_alpha and mod_beta.
    // mod_alpha contains owners {a1, a2}; mod_beta contains {b1, b2}.
    // The constraining edges form an asymmetric cycle between the
    // two modules:
    //   a1 -> b1 (EagerUse, constraining)
    //   b2 -> a2 (EagerUse, constraining)
    // After contracting mod_alpha (a1, a2 share a class) the
    // post-contract quotient has a constraining edge a1-class -> b1
    // and b2 -> a2-class. When the kernel then tries to contract
    // mod_beta (b1 and b2), b1 and b2 would land in one class, and
    // then [a-class, b-class] form a mutual constraining cycle. The
    // gate must reject that contraction.
    let a1 = residual_owner("owner:a1", 1, &["BindingA1"], 5);
    let a2 = residual_owner("owner:a2", 2, &["BindingA2"], 5);
    let b1 = residual_owner("owner:b1", 3, &["BindingB1"], 5);
    let b2 = residual_owner("owner:b2", 4, &["BindingB2"], 5);
    let edges = vec![
        owner_edge("edge:0", "owner:a1", "owner:b1", DepKind::EagerUse, true),
        owner_edge("edge:1", "owner:b2", "owner:a2", DepKind::EagerUse, true),
    ];
    let report = graph_of(
        vec![a1.clone(), a2.clone(), b1.clone(), b2.clone()],
        edges,
        vec![
            atomic_unit_for("atomic:0", &[&a1]),
            atomic_unit_for("atomic:1", &[&a2]),
            atomic_unit_for("atomic:2", &[&b1]),
            atomic_unit_for("atomic:3", &[&b2]),
        ],
        vec![],
    );
    let spec = vec![
        SpecModuleGroup {
            module_id: "mod_alpha".to_string(),
            owner_ids: vec!["owner:a1".to_string(), "owner:a2".to_string()],
        },
        SpecModuleGroup {
            module_id: "mod_beta".to_string(),
            owner_ids: vec!["owner:b1".to_string(), "owner:b2".to_string()],
        },
    ];
    let (q, rejected) = build_seed_quotient(&report, &report.atomic_graph.nodes, &spec, 10_000);

    // Exactly one of the two contractions must be rejected. The
    // canonical order is mod_alpha first (lex), so mod_alpha
    // applies cleanly and mod_beta gets rejected.
    let spec_rejections: Vec<&SeedContractionRejected> = rejected
        .iter()
        .filter(|r| matches!(r, SeedContractionRejected::SpecModule { .. }))
        .collect();
    assert_eq!(
        spec_rejections.len(),
        1,
        "exactly one spec-module rejection expected, got {rejected:?}",
    );
    let SeedContractionRejected::SpecModule {
        module_id,
        rejected_pair,
        cycle,
        ..
    } = spec_rejections[0]
    else {
        panic!("expected SpecModule variant");
    };
    assert_eq!(module_id, "mod_beta");
    assert_eq!(
        rejected_pair,
        &("owner:b1".to_string(), "owner:b2".to_string()),
        "rejection should point at the b1<->b2 contraction",
    );
    assert!(!cycle.is_empty(), "cycle evidence must be non-empty");
    // The cycle evidence must mention both alpha-class owners and
    // the b1-class — the cycle the proposed contraction would join.
    let evidence_owners: Vec<&str> = cycle
        .cycles
        .iter()
        .flat_map(|c| c.owner_ids.iter().map(String::as_str))
        .collect();
    assert!(
        evidence_owners.contains(&"owner:a1") && evidence_owners.contains(&"owner:a2"),
        "cycle evidence should include alpha owners: {evidence_owners:?}",
    );
    assert!(
        evidence_owners.contains(&"owner:b1") || evidence_owners.contains(&"owner:b2"),
        "cycle evidence should include at least one beta owner: {evidence_owners:?}",
    );

    // mod_alpha did apply — a1 and a2 share a class.
    let a1_idx = q.owner_idx_of("owner:a1").unwrap();
    let a2_idx = q.owner_idx_of("owner:a2").unwrap();
    assert_eq!(q.class_of(a1_idx), q.class_of(a2_idx));
    // mod_beta did NOT apply — b1 and b2 are still in distinct
    // classes (the kernel never silently merged them).
    let b1_idx = q.owner_idx_of("owner:b1").unwrap();
    let b2_idx = q.owner_idx_of("owner:b2").unwrap();
    assert_ne!(q.class_of(b1_idx), q.class_of(b2_idx));
}

#[test]
fn seed_atomic_unit_contractions_never_rejected_on_well_formed_input() {
    // Regression guard: across a handful of well-formed fixtures,
    // no atomic-unit contraction is ever rejected. (Spec-module
    // rejections are allowed; we count only the AtomicUnit
    // variants.)
    let fixtures = [
        fixture_singletons(),
        fixture_unit_of_two(),
        fixture_unit_of_three(),
        fixture_two_units_no_edges(),
    ];
    for (label, report) in fixtures {
        let (_q, rejected) = build_seed_quotient(&report, &report.atomic_graph.nodes, &[], 10_000);
        let atomic_rejections: Vec<&SeedContractionRejected> = rejected
            .iter()
            .filter(|r| matches!(r, SeedContractionRejected::AtomicUnit { .. }))
            .collect();
        assert!(
            atomic_rejections.is_empty(),
            "{label}: atomic-unit contractions must never be rejected on well-formed input, got {atomic_rejections:?}",
        );
    }
}

fn fixture_singletons() -> (&'static str, OwnerGraphReport) {
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    (
        "singletons",
        graph_of(
            vec![a.clone(), b.clone()],
            vec![],
            vec![
                atomic_unit_for("atomic:0", &[&a]),
                atomic_unit_for("atomic:1", &[&b]),
            ],
            vec![],
        ),
    )
}

fn fixture_unit_of_two() -> (&'static str, OwnerGraphReport) {
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    (
        "unit_of_two",
        graph_of(
            vec![a.clone(), b.clone()],
            vec![],
            vec![atomic_unit_for("atomic:0", &[&a, &b])],
            vec![],
        ),
    )
}

fn fixture_unit_of_three() -> (&'static str, OwnerGraphReport) {
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    let c = residual_owner("owner:c", 3, &["BindingC"], 5);
    (
        "unit_of_three",
        graph_of(
            vec![a.clone(), b.clone(), c.clone()],
            vec![],
            vec![atomic_unit_for("atomic:0", &[&a, &b, &c])],
            vec![],
        ),
    )
}

fn fixture_two_units_no_edges() -> (&'static str, OwnerGraphReport) {
    let a1 = residual_owner("owner:a1", 1, &["BindingA1"], 5);
    let a2 = residual_owner("owner:a2", 2, &["BindingA2"], 5);
    let b1 = residual_owner("owner:b1", 3, &["BindingB1"], 5);
    let b2 = residual_owner("owner:b2", 4, &["BindingB2"], 5);
    (
        "two_units_no_edges",
        graph_of(
            vec![a1.clone(), a2.clone(), b1.clone(), b2.clone()],
            vec![],
            vec![
                atomic_unit_for("atomic:0", &[&a1, &a2]),
                atomic_unit_for("atomic:1", &[&b1, &b2]),
            ],
            vec![],
        ),
    )
}

#[test]
fn seed_rejection_diagnostic_is_canonical() {
    // Same fixture run twice; rejection diagnostic byte-equal across
    // runs. Determinism check.
    let make_report = || {
        let a1 = residual_owner("owner:a1", 1, &["BindingA1"], 5);
        let a2 = residual_owner("owner:a2", 2, &["BindingA2"], 5);
        let b1 = residual_owner("owner:b1", 3, &["BindingB1"], 5);
        let b2 = residual_owner("owner:b2", 4, &["BindingB2"], 5);
        let edges = vec![
            owner_edge("edge:0", "owner:a1", "owner:b1", DepKind::EagerUse, true),
            owner_edge("edge:1", "owner:b2", "owner:a2", DepKind::EagerUse, true),
        ];
        graph_of(
            vec![a1.clone(), a2.clone(), b1.clone(), b2.clone()],
            edges,
            vec![
                atomic_unit_for("atomic:0", &[&a1]),
                atomic_unit_for("atomic:1", &[&a2]),
                atomic_unit_for("atomic:2", &[&b1]),
                atomic_unit_for("atomic:3", &[&b2]),
            ],
            vec![],
        )
    };
    let spec = vec![
        SpecModuleGroup {
            module_id: "mod_alpha".to_string(),
            owner_ids: vec!["owner:a1".to_string(), "owner:a2".to_string()],
        },
        SpecModuleGroup {
            module_id: "mod_beta".to_string(),
            owner_ids: vec!["owner:b1".to_string(), "owner:b2".to_string()],
        },
    ];

    let report_a = make_report();
    let (_q1, rejected_a) =
        build_seed_quotient(&report_a, &report_a.atomic_graph.nodes, &spec, 10_000);
    let report_b = make_report();
    let (_q2, rejected_b) =
        build_seed_quotient(&report_b, &report_b.atomic_graph.nodes, &spec, 10_000);

    let json_a = serde_json::to_string_pretty(&rejected_a).unwrap();
    let json_b = serde_json::to_string_pretty(&rejected_b).unwrap();
    assert_eq!(
        json_a, json_b,
        "rejection diagnostic must be byte-identical across runs",
    );
}

#[test]
fn contract_never_un_contracts() {
    // API surface check: after a contraction, the involved owners
    // remain in the same class no matter what subsequent operations
    // are performed. There is no public `split` / `un_contract` /
    // `set_class` on QuotientGraph; the only mutation is
    // `contract`, which is monotone (coarsens `~`).
    //
    // We verify this empirically by:
    //   1. Building a fresh quotient.
    //   2. Contracting (c(a), c(b)).
    //   3. Performing every other contraction the kernel allows and
    //      asserting that c(a) == c(b) after each.
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    let c = residual_owner("owner:c", 3, &["BindingC"], 5);
    let d = residual_owner("owner:d", 4, &["BindingD"], 5);
    let report = graph_of(
        vec![a.clone(), b.clone(), c.clone(), d.clone()],
        vec![],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&b]),
            atomic_unit_for("atomic:2", &[&c]),
            atomic_unit_for("atomic:3", &[&d]),
        ],
        vec![],
    );
    let mut q = QuotientGraph::from_report(&report, 10_000);
    let a_idx = q.owner_idx_of("owner:a").unwrap();
    let b_idx = q.owner_idx_of("owner:b").unwrap();
    let c_idx = q.owner_idx_of("owner:c").unwrap();
    let d_idx = q.owner_idx_of("owner:d").unwrap();

    let ca = q.class_of(a_idx);
    let cb = q.class_of(b_idx);
    q.contract(ca, cb).expect("contract(a, b)");
    assert_eq!(q.class_of(a_idx), q.class_of(b_idx));

    // After contracting (c, d), a and b still share a class.
    let cc = q.class_of(c_idx);
    let cd = q.class_of(d_idx);
    q.contract(cc, cd).expect("contract(c, d)");
    assert_eq!(q.class_of(a_idx), q.class_of(b_idx));

    // After contracting (a-class, c-class), all four share a
    // class — a and b are still together.
    let cab = q.class_of(a_idx);
    let ccd = q.class_of(c_idx);
    q.contract(cab, ccd).expect("contract(ab, cd)");
    assert_eq!(q.class_of(a_idx), q.class_of(b_idx));
    assert_eq!(q.class_of(a_idx), q.class_of(c_idx));
    assert_eq!(q.class_of(a_idx), q.class_of(d_idx));
}

#[test]
fn partition_constructor_contracts_each_group() {
    // Internal invariant of the renderer-over-quotient refactor
    // (commit 1b): `from_report_with_partition` materializes a
    // quotient whose equivalence classes are exactly the input
    // groups. This is the bridge between today's cell-discovery
    // pass and the kernel that `emit_proposals` reads.
    //
    // - Owners not listed in any group remain singletons.
    // - Each group's owners share a class.
    // - Cross-group owners are in distinct classes.
    let a = residual_owner("owner:a", 1, &["BindingA"], 5);
    let b = residual_owner("owner:b", 2, &["BindingB"], 5);
    let c = residual_owner("owner:c", 3, &["BindingC"], 5);
    let d = residual_owner("owner:d", 4, &["BindingD"], 5);
    let e = residual_owner("owner:e", 5, &["BindingE"], 5);
    let report = graph_of(
        vec![a.clone(), b.clone(), c.clone(), d.clone(), e.clone()],
        vec![owner_edge(
            "edge:0",
            "owner:a",
            "owner:b",
            DepKind::EagerUse,
            true,
        )],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&b]),
            atomic_unit_for("atomic:2", &[&c]),
            atomic_unit_for("atomic:3", &[&d]),
            atomic_unit_for("atomic:4", &[&e]),
        ],
        vec![],
    );

    // Group 1: {a, b}; group 2: {c, d}; e stays singleton.
    let groups = vec![
        vec![OwnerIdx(0), OwnerIdx(1)],
        vec![OwnerIdx(2), OwnerIdx(3)],
    ];
    let (q, class_ids) = QuotientGraph::from_report_with_partition(&report, 10_000, &groups);
    assert_eq!(class_ids.len(), 2, "one class id per input group");

    let a_idx = q.owner_idx_of("owner:a").unwrap();
    let b_idx = q.owner_idx_of("owner:b").unwrap();
    let c_idx = q.owner_idx_of("owner:c").unwrap();
    let d_idx = q.owner_idx_of("owner:d").unwrap();
    let e_idx = q.owner_idx_of("owner:e").unwrap();

    assert_eq!(q.class_of(a_idx), q.class_of(b_idx), "a/b co-located");
    assert_eq!(q.class_of(c_idx), q.class_of(d_idx), "c/d co-located");
    assert_ne!(
        q.class_of(a_idx),
        q.class_of(c_idx),
        "groups in distinct classes",
    );
    assert_ne!(
        q.class_of(e_idx),
        q.class_of(a_idx),
        "ungrouped owner stays singleton",
    );
    assert_ne!(
        q.class_of(e_idx),
        q.class_of(c_idx),
        "ungrouped owner stays singleton",
    );

    // The returned class ids must point at the actual class of each
    // group's owners (the renderer reads from these).
    assert_eq!(class_ids[0], q.class_of(a_idx));
    assert_eq!(class_ids[1], q.class_of(c_idx));

    // class_lines reflects the sum of members' source line counts.
    // a and b each contribute 5 lines (per residual_owner above).
    assert_eq!(q.class_lines(class_ids[0]), 10);
}

#[test]
fn factorize_golden_output_unchanged() {
    // Golden test for commit 1b: factorize's output is byte-identical
    // to the pre-commit-1 binary's output for the same input. The
    // baselines were captured by running `factorize` on these
    // fixtures at HEAD = 3c75ae9ae (pre-commit-1, post-anon-only
    // extension), then verified to match commit-1's output (which
    // adds the kernel as a pure-side-effect diagnostic, no behavior
    // change). The renderer-over-quotient refactor (this commit)
    // must keep these outputs stable.
    //
    // Each fixture exercises a representative shape:
    //   - `residual_singletons`: two unrelated residual owners,
    //     no edges.
    //   - `closed_residual_unit`: two residual units coupled by
    //     a constraining edge.
    //   - `extend_active_via_anon`: an anonymous statement whose
    //     unique constraining edge points at an active module
    //     (promote_anonymous_only_cell_to_extension path).
    //
    // Snapshots live at `devinfra/js/debundle/peel/golden/`. To
    // regenerate (only after a deliberate, justified change), set
    // `UPDATE_GOLDENS=1` when running the test.
    let claims: BTreeMap<String, String> = BTreeMap::new();
    let f1 = factorize(&golden_residual_singletons(), &claims, 10_000);
    let f2 = factorize(&golden_closed_residual_unit(), &claims, 10_000);
    let claims_active: BTreeMap<String, String> =
        BTreeMap::from([("BindingA".to_string(), "ui/x".to_string())]);
    let f3 = factorize(&golden_extend_active_via_anon(), &claims_active, 10_000);

    let json1 = serde_json::to_string_pretty(&f1).unwrap();
    let json2 = serde_json::to_string_pretty(&f2).unwrap();
    let json3 = serde_json::to_string_pretty(&f3).unwrap();

    // Strip a single trailing newline from each golden file before
    // comparing — JSON formatters and pre-commit hooks routinely
    // add one, while `serde_json::to_string_pretty` doesn't. The
    // semantic content is what we're locking down, not whether
    // pre-commit thinks the file ends in a newline.
    let golden1 = include_str!("golden/residual_singletons.json").trim_end_matches('\n');
    let golden2 = include_str!("golden/closed_residual_unit.json").trim_end_matches('\n');
    let golden3 = include_str!("golden/extend_active_via_anon.json").trim_end_matches('\n');

    assert_eq!(
        json1, golden1,
        "residual_singletons fixture diverged from pre-commit-1 baseline",
    );
    assert_eq!(
        json2, golden2,
        "closed_residual_unit fixture diverged from pre-commit-1 baseline",
    );
    assert_eq!(
        json3, golden3,
        "extend_active_via_anon fixture diverged from pre-commit-1 baseline",
    );
}

fn golden_residual_singletons() -> OwnerGraphReport {
    let a = residual_owner("owner:a", 1, &["BindingA"], 10);
    let b = residual_owner("owner:b", 2, &["BindingB"], 10);
    graph_of(
        vec![a.clone(), b.clone()],
        vec![],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&b]),
        ],
        vec![],
    )
}

fn golden_closed_residual_unit() -> OwnerGraphReport {
    let a = residual_owner("owner:a", 1, &["BindingA"], 10);
    let b = residual_owner("owner:b", 2, &["BindingB"], 10);
    graph_of(
        vec![a.clone(), b.clone()],
        vec![owner_edge(
            "edge:0",
            "owner:a",
            "owner:b",
            DepKind::EagerUse,
            true,
        )],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&b]),
        ],
        vec![atomic_edge("atomic_edge:0", "atomic:0", "atomic:1")],
    )
}

fn golden_extend_active_via_anon() -> OwnerGraphReport {
    // BindingA is in an active module ui/x. An anonymous statement
    // (no declared bindings) has one constraining edge into a.
    // factorize should promote it to extend:ui/x.
    let a = active_owner("owner:a", 1, &["BindingA"], 10, "ui/x");
    let anon = residual_owner("owner:anon", 2, &[], 5);
    graph_of(
        vec![a.clone(), anon.clone()],
        vec![owner_edge(
            "edge:0",
            "owner:anon",
            "owner:a",
            DepKind::EagerUse,
            true,
        )],
        vec![
            atomic_unit_for("atomic:0", &[&a]),
            atomic_unit_for("atomic:1", &[&anon]),
        ],
        vec![atomic_edge("atomic_edge:0", "atomic:1", "atomic:0")],
    )
}
