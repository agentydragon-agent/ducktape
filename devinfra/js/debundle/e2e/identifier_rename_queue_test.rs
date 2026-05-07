//! End-to-end tests for the identifier rename priority queue side
//! output. Drives the real pipeline through a synthetic bundle
//! and asserts on the JSON contract.

use debundle_e2e_support::*;
use serde_json::Value;
use std::fs;

#[test]
fn emits_rename_queue_manifest() {
    // The synthetic bundle has four top-level input-bundle bindings:
    //   - `aH` is referenced 5x within the entry (inside `bC`, `dE`,
    //     and the trailing console.log) so it tops the queue.
    //   - `bC` (a function) references `aH` and is itself referenced 2x.
    //   - `dE` references both `aH` and `bC` and is referenced 1x.
    //   - `getUserData` has a readable spelling, but it is still an
    //     input-bundle name, so the queue must include it until a spec
    //     gives it a new output name. The queue predicate is origin, not
    //     identifier shape.
    //   - `URL` is a builtin acronym shape, but it's a reference to the
    //     global, NOT a top-level binding, so it just doesn't show up.
    let fixture = run_fixture(FixtureOpts::new(
        r#"const aH = "scrambled-most-referenced";
function bC() { return aH + aH; }
const dE = bC() + aH + aH;
function getUserData() { return aH; }
console.log(dE, bC(), getUserData());
export { aH, bC, dE };
"#,
        vec![],
    ));

    let queue = read_queue(&fixture.out_root);
    assert!(
        queue["generated_at_iso"]
            .as_str()
            .expect("generated_at_iso should be a string")
            .ends_with('Z'),
        "expected ISO timestamp ending in Z, got {:?}",
        queue["generated_at_iso"]
    );

    let entries = queue["entries"]
        .as_array()
        .expect("entries must be an array");
    let names: Vec<&str> = entries
        .iter()
        .map(|e| e["name"].as_str().unwrap())
        .collect();

    // All input-bundle top-level bindings must appear, even when the
    // spelling is already readable.
    for needle in ["aH", "bC", "dE", "getUserData"] {
        assert!(
            names.contains(&needle),
            "missing input-bundle name {needle:?} in queue: {names:?}"
        );
    }

    // Queue must be sorted by ref_count desc with fanout_modules tiebreak.
    let ref_counts: Vec<u64> = entries
        .iter()
        .map(|e| e["ref_count"].as_u64().unwrap())
        .collect();
    let mut sorted = ref_counts.clone();
    sorted.sort_by(|a, b| b.cmp(a));
    assert_eq!(
        ref_counts, sorted,
        "entries must be sorted by ref_count descending"
    );

    // Selector is the documented stable-id triple form.
    for entry in entries {
        let selector = entry["selector"].as_str().expect("selector must be string");
        let parts: Vec<&str> = selector.split(':').collect();
        assert_eq!(
            parts.len(),
            3,
            "selector must be <chunk>:<file>:<ordinal> form, got {selector}",
        );
        // ordinal is a non-negative integer
        let _ordinal: usize = parts[2]
            .parse()
            .unwrap_or_else(|e| panic!("selector ordinal must parse as usize: {selector}: {e}"));
        // owner_chunk and owner_file are populated.
        assert!(!entry["owner_chunk"].as_str().unwrap().is_empty());
        assert!(!entry["owner_file"].as_str().unwrap().is_empty());
    }

    // total_references is the sum of the per-entry ref_count.
    let total_refs: u64 = ref_counts.iter().sum();
    assert_eq!(queue["total_references"].as_u64().unwrap(), total_refs);
    assert_eq!(
        queue["total_unrenamed_symbols"].as_u64().unwrap(),
        entries.len() as u64
    );

    // The first entry should be `aH` — it has the highest reference
    // count (5 reads inside the synthetic bundle's body and exports).
    assert_eq!(
        entries[0]["name"].as_str().unwrap(),
        "aH",
        "expected highest ref_count to be `aH`; entries: {entries:#?}",
    );
}

#[test]
fn renamed_members_leave_queue() {
    let fixture = run_fixture(FixtureOpts::new(
        r#"const aH = "renamed";
const bC = aH + aH;
console.log(aH, bC);
export { aH, bC };
"#,
        vec![logical_module(
            "domain/readable",
            &[Member::renamed("readableThing", "aH")],
        )],
    ));

    let queue = read_queue(&fixture.out_root);
    let entries = queue["entries"]
        .as_array()
        .expect("entries must be an array");
    let names: Vec<&str> = entries
        .iter()
        .map(|e| e["name"].as_str().unwrap())
        .collect();
    assert!(
        !names.contains(&"aH"),
        "renamed input binding should not remain queued: {names:?}"
    );
    assert!(
        !names.contains(&"readableThing"),
        "new readable output name should not be queued: {names:?}"
    );
    assert!(
        names.contains(&"bC"),
        "unrenamed companion binding should remain queued: {names:?}"
    );
}

#[test]
fn manifest_records_queue_path() {
    let fixture = run_fixture(FixtureOpts::new(
        r#"const xY = 1;
console.log(xY);
export { xY };
"#,
        vec![],
    ));
    let manifest = read_manifest(&fixture.out_root);
    let path = manifest["identifier_rename_queue"]
        .as_str()
        .expect("manifest must record identifier_rename_queue path");
    assert!(
        !path.starts_with('/') && !path.starts_with(".."),
        "queue path must be manifest-relative, got {path}",
    );
    let resolved = fixture.out_root.join(path);
    assert!(
        resolved.exists(),
        "queue path {path} resolves to {resolved:?} which does not exist",
    );
}

#[test]
fn entries_stay_stable_across_runs() {
    // Stable-selector test: re-running the pipeline against the same
    // synthetic bundle must yield byte-identical `entries` payloads
    // (selectors don't drift, sort is deterministic).
    let first = read_entries_payload(run_fixture(FixtureOpts::new(
        r#"const aH = "stable";
function bC() { return aH; }
const dE = bC();
console.log(dE);
export { aH, bC, dE };
"#,
        vec![],
    )));
    let second = read_entries_payload(run_fixture(FixtureOpts::new(
        r#"const aH = "stable";
function bC() { return aH; }
const dE = bC();
console.log(dE);
export { aH, bC, dE };
"#,
        vec![],
    )));
    assert_eq!(
        first, second,
        "entries payload must be byte-identical across runs",
    );
}

fn read_queue(out_root: &std::path::Path) -> Value {
    let path = out_root.join("identifier-rename-queue.json");
    let raw = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&raw).expect("queue JSON must parse")
}

fn read_manifest(out_root: &std::path::Path) -> Value {
    let path = out_root.join("manifest.json");
    let raw = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&raw).expect("manifest JSON must parse")
}

/// Just the `entries` field — `generated_at_iso` is wall-clock-derived
/// and intentionally varies.
fn read_entries_payload(fixture: Fixture) -> Value {
    let queue = read_queue(&fixture.out_root);
    queue["entries"].clone()
}
