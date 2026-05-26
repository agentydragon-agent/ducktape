//! End-to-end check of `module_cli::merge_modules` against a tempdir
//! fixture. Hits the public Rust function directly so the test does
//! not depend on the built `debundle` binary.

use std::fs;
use std::path::Path;

use module_cli::merge_modules;
use serde_yaml::Value;
use tempfile::TempDir;

fn write(root: &Path, rel: &str, body: &str) {
    let path = root.join(rel);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    fs::write(path, body).unwrap();
}

fn member_names(doc: &Value) -> Vec<String> {
    doc["members"]
        .as_sequence()
        .expect("members sequence")
        .iter()
        .map(|m| {
            m["selector"]["binding"]["name"]
                .as_str()
                .expect("name")
                .to_string()
        })
        .collect()
}

#[test]
fn merges_two_sources_into_target_and_deletes_sources() {
    let dir = TempDir::new().unwrap();
    let root = dir.path();

    write(
        root,
        "ui/target.yaml",
        "members:\n  - selector: { binding: { name: alpha } }\n",
    );
    write(
        root,
        "ui/src1.yaml",
        "members:\n  - selector: { binding: { name: bravo } }\n",
    );
    write(
        root,
        "ui/src2.yaml",
        "members:\n  - selector: { binding: { name: charlie } }\n",
    );

    let summary = merge_modules(
        root,
        Path::new("ui/target.yaml"),
        &[Path::new("ui/src1.yaml"), Path::new("ui/src2.yaml")],
    )
    .expect("merge succeeds");

    assert_eq!(summary.merged_sources.len(), 2);
    let line = summary.summary_line();
    assert!(line.contains("merged 2 source(s) into"), "line={line}");
    assert!(line.contains("ui/target.yaml"), "line={line}");

    assert!(!root.join("ui/src1.yaml").exists());
    assert!(!root.join("ui/src2.yaml").exists());
    assert!(root.join("ui/target.yaml").exists());

    let merged_text = fs::read_to_string(root.join("ui/target.yaml")).unwrap();
    assert!(
        merged_text.contains("# merged from: ui/src1.yaml, ui/src2.yaml"),
        "missing provenance comment in:\n{merged_text}"
    );
    let merged: Value = serde_yaml::from_str(&merged_text).unwrap();
    assert_eq!(member_names(&merged), vec!["alpha", "bravo", "charlie"]);
}

#[test]
fn duplicate_member_name_across_sources_errors_and_keeps_sources() {
    let dir = TempDir::new().unwrap();
    let root = dir.path();

    write(
        root,
        "target.yaml",
        "members:\n  - selector: { binding: { name: keep } }\n",
    );
    write(
        root,
        "a.yaml",
        "members:\n  - selector: { binding: { name: collide } }\n",
    );
    write(
        root,
        "b.yaml",
        "members:\n  - selector: { binding: { name: collide } }\n",
    );

    let err = merge_modules(
        root,
        Path::new("target.yaml"),
        &[Path::new("a.yaml"), Path::new("b.yaml")],
    )
    .expect_err("collision must error");
    let msg = format!("{err}");
    assert!(
        msg.contains("duplicate member name \"collide\""),
        "msg={msg}"
    );

    // Sources must remain on disk after a failed merge so the author
    // can fix the conflict and re-run.
    assert!(root.join("a.yaml").exists());
    assert!(root.join("b.yaml").exists());
}
