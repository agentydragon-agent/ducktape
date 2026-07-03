use std::fs;

use debundle_e2e_support::{
    BindingGroup, FixtureOpts, Member, logical_module, logical_module_with_anon,
    logical_module_with_anon_alpha_many, logical_module_with_binding_groups,
    run_keep_going_dry_run_rejection_fixture,
};
use serde_json::Value;

#[test]
fn keep_going_writes_machine_readable_selector_diagnostics_report() {
    let missing_selector = r#"function selectedFormatter(value) {
  return value.toLowerCase();
}"#;
    let ambiguous_selector = r#"function repeatedHelper() {
  return "shared";
}"#;
    let opts = FixtureOpts::new(
        r#"function renderCard(value) {
  return value.trim();
}
function decoratePrimary() {
  return "shared";
}
function decorateSecondary() {
  return "shared";
}
console.log(renderCard(" ok "), decoratePrimary(), decorateSecondary());
export { renderCard, decoratePrimary, decorateSecondary };
"#,
        vec![
            logical_module(
                "diagnostics/missing",
                &[Member::source_alpha("MissingFormatter", missing_selector)],
            ),
            logical_module("owners/card", &[Member::new("renderCard")]),
            logical_module(
                "duplicates/card",
                &[Member::renamed("renderCardAgain", "renderCard")],
            ),
            logical_module(
                "diagnostics/ambiguous",
                &[Member::source_alpha("AmbiguousHelper", ambiguous_selector)],
            ),
            logical_module_with_anon("diagnostics/anon", &[], &["console.warn(\"absent\");"]),
        ],
    );

    let rejected = run_keep_going_dry_run_rejection_fixture(opts);
    assert!(
        rejected
            .stderr
            .contains("Source-match selector diagnostic report: 2 unresolved selector(s) found"),
        "human source-match diagnostics must remain intact:\n{}",
        rejected.stderr
    );
    assert!(
        rejected
            .stderr
            .contains("Duplicate binding claim report: 1 duplicate claim(s) found"),
        "human duplicate diagnostics must remain intact:\n{}",
        rejected.stderr
    );
    assert!(
        rejected
            .stderr
            .contains("Anonymous statement selector diagnostic report"),
        "human anonymous diagnostics must appear:\n{}",
        rejected.stderr
    );

    let report_path = rejected
        .report_root
        .join("static")
        .join("app")
        .join("selector_diagnostics.json");
    let report: Value = serde_json::from_str(
        &fs::read_to_string(&report_path)
            .unwrap_or_else(|error| panic!("read {}: {error}", report_path.display())),
    )
    .unwrap();
    assert_eq!(report["chunk_id"], "static/app");
    assert_eq!(report["counts"]["unresolved_selector"], 1);
    assert_eq!(report["counts"]["selector_resolution_error"], 2);
    assert_eq!(report["counts"]["duplicate_claim"], 1);

    let diagnostics = report["diagnostics"]
        .as_array()
        .expect("diagnostics must be an array");
    assert_eq!(diagnostics.len(), 4, "{report:#}");

    let missing = find_entry(diagnostics, "selector_resolution_error", "MissingFormatter");
    assert_eq!(missing["module_path"], "diagnostics/missing");
    assert_eq!(missing["selector_kind"], "members.source_match");
    assert!(missing["target_binding"].is_null(), "{missing:#}");
    assert!(
        missing["source_match_preview"]
            .as_str()
            .unwrap()
            .contains("selectedFormatter"),
        "{missing:#}"
    );
    assert!(
        missing["source_match_hash"].as_str().unwrap().len() >= 16,
        "{missing:#}"
    );
    assert!(
        missing["first_mismatch"]
            .as_str()
            .is_some_and(|s| !s.is_empty()),
        "{missing:#}"
    );
    assert!(
        missing["recommended_next_action"]
            .as_str()
            .unwrap()
            .contains("Inspect the selector error"),
        "{missing:#}"
    );

    let ambiguous = find_entry(diagnostics, "selector_resolution_error", "AmbiguousHelper");
    assert_eq!(ambiguous["module_path"], "diagnostics/ambiguous");
    assert_eq!(ambiguous["body_indices"], serde_json::json!([]));
    assert!(
        ambiguous["message"]
            .as_str()
            .unwrap()
            .contains("valid global selector assignment"),
        "{ambiguous:#}"
    );
    assert!(
        ambiguous["recommended_next_action"]
            .as_str()
            .unwrap()
            .contains("Inspect the selector error"),
        "{ambiguous:#}"
    );

    let duplicate = diagnostics
        .iter()
        .find(|entry| entry["category"] == "duplicate_claim")
        .expect("duplicate claim entry");
    assert_eq!(duplicate["duplicate_claim"]["binding"], "renderCard");
    let duplicate_sites = [
        duplicate["duplicate_claim"]["existing"]["module_id"]
            .as_str()
            .unwrap(),
        duplicate["duplicate_claim"]["duplicate"]["module_id"]
            .as_str()
            .unwrap(),
    ];
    assert!(duplicate_sites.contains(&"static/app::owners/card"));
    assert!(duplicate_sites.contains(&"static/app::duplicates/card"));

    let anon = diagnostics
        .iter()
        .find(|entry| entry["selector_kind"] == "anonymous_statements.source_match")
        .expect("anonymous statement diagnostic entry");
    assert_eq!(anon["category"], "unresolved_selector");
    assert_eq!(anon["module_path"], "diagnostics/anon");
    assert!(anon["export_name"].is_null(), "{anon:#}");
    assert!(
        anon["source_match_preview"]
            .as_str()
            .unwrap()
            .contains("console.warn"),
        "{anon:#}"
    );
}

#[test]
fn keep_going_marks_known_unsat_roots_and_cascades() {
    let missing_selector = r#"function missingFormatter(value) {
  return value.toLowerCase();
}"#;
    let valid_selector = r#"function keepMe(value) {
  return value.trim();
}"#;
    let opts = FixtureOpts::new(
        r#"function keepMe(value) {
  return value.trim();
}
console.log(keepMe(" ok "));
export { keepMe };
"#,
        vec![
            logical_module(
                "diagnostics/root",
                &[Member::source_alpha("MissingFormatter", missing_selector)],
            ),
            logical_module(
                "diagnostics/cascade",
                &[Member::source_alpha("KeepMe", valid_selector)],
            ),
        ],
    );

    let rejected = run_keep_going_dry_run_rejection_fixture(opts);
    assert!(
        rejected.stderr.contains("root_unsat_candidate"),
        "human diagnostics must mark root candidates:\n{}",
        rejected.stderr
    );
    assert!(
        rejected.stderr.contains("cascaded_from_known_unsat"),
        "human diagnostics must mark cascaded targets:\n{}",
        rejected.stderr
    );

    let report_path = rejected
        .report_root
        .join("static")
        .join("app")
        .join("selector_diagnostics.json");
    let report: Value = serde_json::from_str(
        &fs::read_to_string(&report_path)
            .unwrap_or_else(|error| panic!("read {}: {error}", report_path.display())),
    )
    .unwrap();
    let diagnostics = report["diagnostics"]
        .as_array()
        .expect("diagnostics must be an array");

    let root = find_entry(diagnostics, "selector_resolution_error", "MissingFormatter");
    assert_eq!(
        root["root_isolation"]["classification"], "root_unsat_candidate",
        "{root:#}"
    );
    assert!(
        root["root_isolation"]["known_unsat_reason"]
            .as_str()
            .unwrap()
            .contains("variable restriction has empty domain"),
        "{root:#}"
    );
    assert!(
        root["root_isolation"]["implicated_debug_name"]
            .as_str()
            .unwrap()
            .contains("diagnostics/root::source_match.MissingFormatter."),
        "{root:#}"
    );

    let cascade = find_entry(diagnostics, "selector_resolution_error", "KeepMe");
    assert_eq!(
        cascade["root_isolation"]["classification"], "cascaded_from_known_unsat",
        "{cascade:#}"
    );
    assert!(
        cascade["root_isolation"]["known_unsat_reason"]
            .as_str()
            .unwrap()
            .contains("variable restriction has empty domain"),
        "{cascade:#}"
    );
}

#[test]
fn keep_going_matches_known_unsat_anonymous_roots_by_index() {
    let opts = FixtureOpts::new(
        r#"console.log("present");
"#,
        vec![logical_module_with_anon_alpha_many(
            "diagnostics/anon",
            &[],
            &[r#"console.warn("missing");"#, r#"console.log("present");"#],
        )],
    );

    let rejected = run_keep_going_dry_run_rejection_fixture(opts);
    let report_path = rejected
        .report_root
        .join("static")
        .join("app")
        .join("selector_diagnostics.json");
    let report: Value = serde_json::from_str(
        &fs::read_to_string(&report_path)
            .unwrap_or_else(|error| panic!("read {}: {error}", report_path.display())),
    )
    .unwrap();
    let diagnostics = report["diagnostics"]
        .as_array()
        .expect("diagnostics must be an array");

    let root = find_anon_entry(diagnostics, "console.warn");
    assert_eq!(
        root["root_isolation"]["classification"], "root_unsat_candidate",
        "{root:#}"
    );
    assert!(
        root["root_isolation"]["implicated_debug_name"]
            .as_str()
            .unwrap()
            .contains("diagnostics/anon::anonymous_statement.0.source_match."),
        "{root:#}"
    );

    let cascade = find_anon_entry(diagnostics, "console.log");
    assert_eq!(
        cascade["root_isolation"]["classification"], "cascaded_from_known_unsat",
        "{cascade:#}"
    );
}

#[test]
fn keep_going_matches_known_unsat_binding_group_roots_by_target_binding() {
    let opts = FixtureOpts::new(
        r#"const presentLeft = 1, presentRight = 2;
console.log(presentLeft, presentRight);
export { presentLeft, presentRight };
"#,
        vec![logical_module_with_binding_groups(
            "diagnostics/group",
            &[],
            &[BindingGroup::source_alpha(
                r#"const missingLeft = "missing-left", missingRight = "missing-right";"#,
                &[
                    ("missingLeft", "ExportedLeft"),
                    ("missingRight", "ExportedRight"),
                ],
            )],
        )],
    );

    let rejected = run_keep_going_dry_run_rejection_fixture(opts);
    let report_path = rejected
        .report_root
        .join("static")
        .join("app")
        .join("selector_diagnostics.json");
    let report: Value = serde_json::from_str(
        &fs::read_to_string(&report_path)
            .unwrap_or_else(|error| panic!("read {}: {error}", report_path.display())),
    )
    .unwrap();
    let diagnostics = report["diagnostics"]
        .as_array()
        .expect("diagnostics must be an array");

    let left = find_entry(diagnostics, "selector_resolution_error", "ExportedLeft");
    assert_eq!(left["selector_kind"], "binding_groups.source_match");
    assert_eq!(
        left["root_isolation"]["classification"], "root_unsat_candidate",
        "{left:#}"
    );
    assert!(
        left["root_isolation"]["implicated_debug_name"]
            .as_str()
            .unwrap()
            .contains("diagnostics/group::binding_group.source_match.missingLeft,missingRight."),
        "{left:#}"
    );

    let right = find_entry(diagnostics, "selector_resolution_error", "ExportedRight");
    assert_eq!(right["selector_kind"], "binding_groups.source_match");
    assert_eq!(
        right["root_isolation"]["classification"], "root_unsat_candidate",
        "{right:#}"
    );
}

#[test]
fn keep_going_reports_unsupported_binding_group_source_match() {
    let opts = FixtureOpts::new(
        r#"const present = 1;
console.log(present);
export { present };
"#,
        vec![logical_module_with_binding_groups(
            "diagnostics/unsupported-group",
            &[],
            &[BindingGroup::source_alpha(
                "STMT_LIST;",
                &[("left", "ExportedLeft"), ("right", "ExportedRight")],
            )],
        )],
    );

    let rejected = run_keep_going_dry_run_rejection_fixture(opts);
    assert!(
        rejected
            .stderr
            .contains("binding_groups[].source_match for target bindings [left, right]"),
        "human diagnostics should report the unsupported group:\n{}",
        rejected.stderr
    );
    let report_path = rejected
        .report_root
        .join("static")
        .join("app")
        .join("selector_diagnostics.json");
    let report: Value = serde_json::from_str(
        &fs::read_to_string(&report_path)
            .unwrap_or_else(|error| panic!("read {}: {error}", report_path.display())),
    )
    .unwrap();
    let diagnostics = report["diagnostics"]
        .as_array()
        .expect("diagnostics must be an array");

    let left = find_entry(diagnostics, "selector_resolution_error", "ExportedLeft");
    assert_eq!(left["selector_kind"], "binding_groups.source_match");
    assert_eq!(left["target_binding"], "left");
    assert!(
        left["message"]
            .as_str()
            .unwrap()
            .contains("cannot be lowered into native selector IR"),
        "{left:#}"
    );
    let right = find_entry(diagnostics, "selector_resolution_error", "ExportedRight");
    assert_eq!(right["selector_kind"], "binding_groups.source_match");
    assert_eq!(right["target_binding"], "right");
}

fn find_entry<'a>(diagnostics: &'a [Value], category: &str, export_name: &str) -> &'a Value {
    diagnostics
        .iter()
        .find(|entry| entry["category"] == category && entry["export_name"] == export_name)
        .unwrap_or_else(|| {
            panic!("missing {category} entry for export {export_name}: {diagnostics:#?}")
        })
}

fn find_anon_entry<'a>(diagnostics: &'a [Value], preview_needle: &str) -> &'a Value {
    diagnostics
        .iter()
        .find(|entry| {
            entry["selector_kind"] == "anonymous_statements.source_match"
                && entry["source_match_preview"]
                    .as_str()
                    .is_some_and(|preview| preview.contains(preview_needle))
        })
        .unwrap_or_else(|| {
            panic!("missing anonymous entry containing {preview_needle}: {diagnostics:#?}")
        })
}
