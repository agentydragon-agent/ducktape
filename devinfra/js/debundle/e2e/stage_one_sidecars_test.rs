//! Stage A on-disk sidecar writers (v1, in-process inspection).
//!
//! `materialize_logical_chunk` snapshots the per-chunk Stage A analysis
//! to `<report_out_dir>/<chunk_id>/chunk_analysis/` whenever the
//! pipeline runs with a report directory. This test pins the sidecar
//! contract end-to-end: a small fixture spec produces the v1 sibling
//! files (facts + atomic_units + manifest), the manifest carries the
//! expected envelope shape, and each payload deserializes back into
//! the native type.
//!
//! v1 intentionally does NOT write `ast.json`. The SWC `Module`
//! requires `Globals`-portable hygiene to be useful in a separate-
//! process Stage B; v1 defers that wire-format redesign and keeps the
//! sidecars scoped to in-process inspection. See
//! `stage_one/sidecars.rs` docstring for the rationale.

use std::fs;

use analysis::{AtomicUnit, ChunkAnalysisManifest, ChunkFactsReport};
use debundle_e2e_support::*;

/// Helper: read and deserialize a sidecar file at
/// `<chunk_analysis_dir>/<name>`. Wraps both the read and the parse
/// error in a panic that surfaces the path + payload preview so a
/// shape regression is debuggable without rerunning.
fn read_sidecar<T: serde::de::DeserializeOwned>(
    chunk_analysis_dir: &std::path::Path,
    name: &str,
) -> T {
    let path = chunk_analysis_dir.join(name);
    let body =
        fs::read_to_string(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    serde_json::from_str(&body).unwrap_or_else(|err| {
        let preview: String = body.chars().take(400).collect();
        panic!(
            "parse {}: {err}\nfirst 400 bytes:\n{preview}",
            path.display()
        )
    })
}

#[test]
fn stage_one_sidecars_are_written_under_chunk_analysis_dir() {
    // Fixture mirrors `realizability_test::owner_graph_report_is_written_for_successful_specs`:
    // two named bindings + a lazy-read function so the Stage A
    // analysis surfaces non-trivial facts (declared bindings, lazy
    // reads) and at least one structural atomic unit.
    let fixture = run_fixture(FixtureOpts::new(
        r#"const A = "a-value";
const B = "b-value";
function readA() { return A; }
function readB() { return B; }
console.log(readA(), readB());
export { A, B, readA, readB };
"#,
        vec![
            logical_module("mod_a", &[Member::new("A"), Member::new("readB")]),
            logical_module("mod_b", &[Member::new("B"), Member::new("readA")]),
        ],
    ));
    assert_entry_output(&fixture, "a-value b-value\n");

    let chunk_analysis_dir = fixture.report_root.join("static/app/chunk_analysis");
    assert!(
        chunk_analysis_dir.is_dir(),
        "chunk_analysis directory should be created at {}",
        chunk_analysis_dir.display(),
    );

    // Manifest: pinned schema version, chunk id, sibling filenames.
    let manifest: ChunkAnalysisManifest = read_sidecar(&chunk_analysis_dir, "manifest.json");
    assert_eq!(
        manifest.schema_version, 1,
        "manifest schema_version is v1 (initial)",
    );
    assert_eq!(
        manifest.chunk_id, "static/app",
        "manifest carries the fixture's chunk id",
    );
    assert!(
        manifest.paths.iter().any(|p| p == "facts.json"),
        "manifest lists facts.json: {:?}",
        manifest.paths,
    );
    assert!(
        manifest.paths.iter().any(|p| p == "atomic_units.json"),
        "manifest lists atomic_units.json: {:?}",
        manifest.paths,
    );

    // v1 explicitly does NOT write ast.json (deferred wire-format
    // redesign — see stage_one/sidecars.rs docstring).
    assert!(
        !chunk_analysis_dir.join("ast.json").exists(),
        "ast.json must not be written in v1",
    );
    assert!(
        !manifest.paths.iter().any(|p| p == "ast.json"),
        "manifest must not list ast.json in v1: {:?}",
        manifest.paths,
    );

    // Facts: round-trips through `ChunkFactsReport`; the fixture has
    // multiple top-level statements so the facts list is non-empty.
    let facts: ChunkFactsReport = read_sidecar(&chunk_analysis_dir, "facts.json");
    assert_eq!(facts.schema_version, 1, "facts schema_version is v1");
    assert!(
        !facts.facts.is_empty(),
        "facts list should carry per-statement records",
    );

    // Atomic units: deserializes as `Vec<AtomicUnit>`. The structural
    // atomic units are exactly what `materialize_from_analysis` (task
    // #78) will need to pick Stage B back up.
    let atomic_units: Vec<AtomicUnit> = read_sidecar(&chunk_analysis_dir, "atomic_units.json");
    assert!(
        !atomic_units.is_empty(),
        "fixture should produce at least one structural atomic unit",
    );
}
