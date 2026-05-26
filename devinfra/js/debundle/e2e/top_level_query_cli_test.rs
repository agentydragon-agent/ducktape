//! End-to-end exercise of the lifted top-level query commands:
//! `debundle atoms`, `coverage`, `graph-summary`, `describe <id>`,
//! `show-source <id>`, `modules propose`.
//!
//! Calls the library entry points directly (no binary execution) so
//! the test runs in-process and stays fast.

use std::fs;
use std::path::Path;

use analysis::{
    AtomicGraphReport, AtomicUnitReport, BindingReport, DepKind, ModuleReportRef,
    OwnerGraphEdgeReport, OwnerGraphNodeReport, OwnerGraphQuotientReport, OwnerGraphReport,
    Purity, QuotientSccReport, SourceLocation, StatementKind, StatementOrdinal,
};
use peel::{
    CommonArgs, ExplainArgs, GraphSummaryArgs, PatchPlanArgs, PlanWorkArgs, SelectionArgs,
    SourceSliceArgs, UnitsArgs, run_explain_report, run_graph_summary_report,
    run_patch_plan_report, run_plan_work_report, run_source_slice_report, run_units_report,
};
use tempfile::TempDir;

fn write(path: &Path, body: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    fs::write(path, body).unwrap();
}

fn member(binding: &str, export: &str) -> BindingReport {
    BindingReport {
        binding: binding.into(),
        export_name: export.into(),
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

fn owner(id: &str, ordinal: usize, binding: &str, export: &str) -> OwnerGraphNodeReport {
    OwnerGraphNodeReport {
        id: id.to_string(),
        statement_ordinal: StatementOrdinal(ordinal),
        source_location: Some(SourceLocation {
            source_path: "static/index.js".to_string(),
            start_line: ordinal + 1,
            end_line: ordinal + 1,
        }),
        declared_bindings: vec![member(binding, export)],
        statement_kind: StatementKind::VarDecl,
        purity: Purity::Pure,
        destination: module_ref("logical:residual", true),
    }
}

fn fixture() -> (TempDir, CommonArgs) {
    let dir = TempDir::new().unwrap();
    let graph_path = dir.path().join("owner_graph.json");
    let modules_root = dir.path().join("spec/modules");
    let zz = owner("owner:0", 1, "ZZ", "ZZ");
    let aa = owner("owner:1", 2, "aa", "aa");
    let report = OwnerGraphReport {
        chunk_id: "static/index".to_string(),
        nodes: vec![zz.clone(), aa.clone()],
        edges: vec![OwnerGraphEdgeReport {
            id: "edge:0".to_string(),
            source: "owner:1".to_string(),
            target: "owner:0".to_string(),
            edge_kind: DepKind::EagerUse,
            binding: Some("ZZ".into()),
            statement_ordinal: StatementOrdinal(2),
            constrains_init_order: true,
            at_init_callee_owner: None,
        }],
        quotient: OwnerGraphQuotientReport {
            nodes: Vec::new(),
            edges: Vec::new(),
            sccs: Vec::<QuotientSccReport>::new(),
        },
        atomic_graph: AtomicGraphReport {
            nodes: vec![
                AtomicUnitReport {
                    id: "atomic:0".to_string(),
                    owner_ids: vec!["owner:0".to_string()],
                    members: vec![member("ZZ", "ZZ")],
                    anonymous_statement_owner_ids: Vec::new(),
                    destinations: vec![module_ref("logical:residual", true)],
                    causes: Vec::new(),
                    size_lines_estimate: 1,
                    source_line_range: Some([2, 2]),
                    ordinal_span: 0,
                },
                AtomicUnitReport {
                    id: "atomic:1".to_string(),
                    owner_ids: vec!["owner:1".to_string()],
                    members: vec![member("aa", "aa")],
                    anonymous_statement_owner_ids: Vec::new(),
                    destinations: vec![module_ref("logical:residual", true)],
                    causes: Vec::new(),
                    size_lines_estimate: 1,
                    source_line_range: Some([3, 3]),
                    ordinal_span: 0,
                },
            ],
            edges: Vec::new(),
        },
    };
    write(&graph_path, &serde_json::to_string(&report).unwrap());
    write(&modules_root.join(".keep"), "");
    write(
        &dir.path().join("static/index.js"),
        "const first = 1;\nconst ZZ = class PaymentError {};\nconst aa = ZZ;\n",
    );
    (
        dir,
        CommonArgs {
            owner_graph_path: graph_path,
            modules_root,
        },
    )
}

#[test]
fn atoms_lists_units() {
    let (_dir, common) = fixture();
    let report = run_units_report(&UnitsArgs {
        common,
        limit: 0,
        residual_only: false,
        readable_only: false,
        by_destination: false,
        format: None,
    })
    .unwrap();
    assert_eq!(report.units.len(), 2);
}

#[test]
fn coverage_reports_summary() {
    let (_dir, common) = fixture();
    let report = run_patch_plan_report(&PatchPlanArgs {
        common,
        limit: 0,
        format: None,
    })
    .unwrap();
    // With no claimed modules, every atom shows up as a missing patch
    // set. Smoke-test that the summary has counts and the rows vector
    // is well-formed.
    assert_eq!(report.summary.total_patch_sets, report.rows.len());
}

#[test]
fn graph_summary_reports_counts() {
    let (_dir, common) = fixture();
    let report = run_graph_summary_report(&GraphSummaryArgs {
        common,
        size_cap_lines: 10_000,
        limit: 10,
        format: None,
    })
    .unwrap();
    assert_eq!(report.owner_count, 2);
    assert_eq!(report.atomic_unit_count, 2);
}

#[test]
fn modules_propose_emits_plan_work_report() {
    let (_dir, common) = fixture();
    let report = run_plan_work_report(&PlanWorkArgs {
        common,
        size_cap_lines: 10_000,
        limit: 0,
        format: None,
    })
    .unwrap();
    // Smoke-test: a fresh fixture with two atoms and a single edge
    // should produce at least one proposal.
    assert!(report.report.proposals.len() >= 1);
}

#[test]
fn describe_binding_resolves_via_selection() {
    let (_dir, common) = fixture();
    let report = run_explain_report(&ExplainArgs {
        common,
        selection: SelectionArgs {
            owner_id: None,
            binding_id: Some("ZZ".to_string()),
            proposal_id: None,
            unit_id: None,
            diagnostic_id: None,
        },
        size_cap_lines: 10_000,
        limit: 0,
        format: None,
    })
    .unwrap();
    assert_eq!(report.owner_ids, vec!["owner:0"]);
    assert_eq!(report.atomic_units[0].id, "atomic:0");
}

#[test]
fn show_source_binding_resolves_via_selection() {
    let (dir, common) = fixture();
    let report = run_source_slice_report(&SourceSliceArgs {
        common,
        selection: SelectionArgs {
            owner_id: None,
            binding_id: Some("ZZ".to_string()),
            proposal_id: None,
            unit_id: None,
            diagnostic_id: None,
        },
        size_cap_lines: 10_000,
        context_lines: 1,
        source_root: Some(dir.path().to_path_buf()),
        format: None,
    })
    .unwrap();
    assert_eq!(report.slices.len(), 1);
    assert!(report.slices[0].text.contains("class PaymentError"));
}
