//! Real JS/spec workflows for assignment validation and atomic edits.

use debundle_e2e_support::{GraphFixture, run_debundle};
use std::fs;

#[test]
fn bindings_assign_rejects_atom_split_in_both_modes_without_writes() {
    GraphFixture::atomic_pair().assert_rejected_unchanged(
        &["bindings", "assign", "alpha:dogfood/split"],
        &["splits one or more atomic units"],
    );
}

#[test]
fn bindings_assign_accepts_acyclic_cross_module_move() {
    let fixture = GraphFixture::acyclic_pair();
    fixture.assert_success(&["bindings", "assign", "beta:c"]);
    assert!(fixture.modules.join("c.yaml").exists());
    assert!(!fixture.modules.join("b.yaml").exists(), "drained source must be deleted");
    fixture.assert_runs("2\n");
}

#[test]
fn bindings_assign_and_unassign_require_graph_or_no_verify() {
    let fixture = GraphFixture::acyclic_pair();
    let before = fs::read(fixture.modules.join("a.yaml")).unwrap();
    for (verb, binding) in [("assign", "alpha:c"), ("unassign", "alpha")] {
        // Deliberately bypass GraphFixture::command, which supplies --graph.
        let out = run_debundle(&["bindings", verb, "--modules", fixture.modules.to_str().unwrap(), binding]);
        assert!(!out.status.success());
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(stderr.contains("--graph") || stderr.contains("--no-verify"), "{stderr}");
        assert_eq!(fs::read(fixture.modules.join("a.yaml")).unwrap(), before);
        assert!(!fixture.modules.join("c.yaml").exists());
    }
}

#[test]
fn assign_rejects_readable_name_claimed_by_source_match_before_writing() {
    let fixture = GraphFixture::new(
        "const alpha = 1;\nconst beta = alpha;\nconsole.log(beta);\n",
        &[
            ("a.yaml", "members: [{selector: {binding: {name: alpha}}}]\n"),
            ("b.yaml", "source_matches: [{match: 'const beta = alpha;', bindings: [{local: beta, name: Existing}]}]\n"),
        ],
    );
    fixture.assert_rejected_unchanged(
        &["bindings", "assign", "alpha:c:Existing"],
        &["name collision", "source_matches[0].bindings[0]"],
    );
}
