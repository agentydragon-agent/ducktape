//! On-disk sidecar writers for Stage A artifacts (v1, in-process).
//!
//! Stage A (see `stage_one.rs` and DESIGN.md §"Pipeline split (Stage A /
//! Stage B)") is the spec-independent half of the per-chunk pipeline.
//! This module writes a subset of its outputs — per-statement facts,
//! the structural atomic units, plus a manifest — as sibling JSON
//! files under `reports/tree/<chunk_id>/chunk_analysis/`. The sidecars
//! are emitted from inside the materializer alongside the other
//! per-chunk reports; they're consumed by `peel`-family CLI tooling
//! and by humans inspecting the pipeline.
//!
//! ## Out of scope for v1
//!
//! **No `ast.json`.** Serializing the SWC `Module` requires the
//! `swc_ecma_ast/serde-impl` feature (enabled in MODULE.bazel) and
//! round-trips through `serde_json`, but `Id = (Atom, SyntaxContext)`
//! values carry a `SyntaxContext` whose `u32` is meaningful only within
//! the SWC `Globals` instance that produced it. A reader in a *separate
//! process* — the cacheable-action target the full pipeline split is
//! aiming for — cannot make those identities line up with its own
//! `top_level_id`-resolved bindings without a structural change to the
//! wire format (drop `ctxt`, carry a scope discriminator, reconstruct
//! `Id`s post-resolver in the reader). That redesign is deferred. See
//! `ARCH_REVIEW_2026_05.md` §"Pipeline-split risks" for the analysis.
//!
//! Until that redesign lands, v1's sidecars are designed for **in-
//! process inspection**: a CLI tool or a debugging human reads them
//! during the same materializer run that produced them, where the
//! shared `Globals` makes the `Id` identities valid. A separate-process
//! `materialize_from_analysis` reader (task #78) is blocked on the wire
//! format redesign.
//!
//! ## File layout
//!
//! Given `report_out_dir = <reports>/tree`, this writer creates a
//! `<chunk_id>/chunk_analysis/` directory holding three sibling files:
//!
//! - `facts.json`        — a `ChunkFactsReport` (see `facts/wire.rs`)
//!   round-trippable back into `ChunkFactAnalysis` *within the same
//!   `Globals` scope*.
//! - `atomic_units.json` — the `Vec<AtomicUnit>` from
//!   `OwnerGraphAndUnits` (already `Serialize`).
//! - `manifest.json`     — a small envelope with `schema_version`,
//!   `chunk_id`, and the sibling filenames a reader should expect.
//!
//! Each file is written pretty-printed; sizes are bounded by chunk
//! size.
//!
//! ## Why a manifest
//!
//! The manifest pins the on-disk filenames and a `schema_version` so a
//! reader can fail fast on shape drift without probing for every
//! sibling file. The `paths` array intentionally lists the companion
//! filenames (not absolute paths) so the artifact is relocatable — a
//! reader resolves them relative to the manifest's parent directory.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

use output_layout::{
    CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT, CHUNK_ANALYSIS_DIR, CHUNK_ANALYSIS_FACTS_REPORT,
    CHUNK_ANALYSIS_MANIFEST_REPORT,
};

use crate::StageOneAnalysis;
use crate::facts::ChunkFactsReport;

/// Current schema version of the chunk-analysis manifest. Bump on any
/// breaking change to the sidecar set (renamed file, dropped file,
/// changed payload shape that isn't itself versioned).
pub const CHUNK_ANALYSIS_MANIFEST_SCHEMA_VERSION: u32 = 1;

/// Manifest envelope written alongside the per-concept sidecars. Pins
/// the schema version, identifies the chunk, and lists the sibling
/// filenames a reader should expect — see module docstring for the
/// rationale.
#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChunkAnalysisManifest {
    pub schema_version: u32,
    pub chunk_id: String,
    pub paths: Vec<String>,
}

impl ChunkAnalysisManifest {
    /// Build the manifest with the canonical sibling filenames in a
    /// stable order. Keeping the order deterministic helps text-diff
    /// review of the on-disk artifact.
    pub fn new(chunk_id: &str) -> Self {
        Self {
            schema_version: CHUNK_ANALYSIS_MANIFEST_SCHEMA_VERSION,
            chunk_id: chunk_id.to_string(),
            paths: vec![
                CHUNK_ANALYSIS_FACTS_REPORT.to_string(),
                CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT.to_string(),
            ],
        }
    }
}

/// Write the v1 Stage A sidecars to
/// `<report_out_dir>/<chunk_id>/chunk_analysis/`.
///
/// `report_out_dir` is the *tree root* (the same path `materialize_*`
/// passes to `write_chunk_report_json`). The `chunk_id` is interpreted
/// as a `/`-separated subpath so chunk ids like `static/app` nest
/// correctly under the tree root — matching the convention every
/// other chunk-report writer in the crate uses.
///
/// v1 writes three sidecars (facts, atomic_units, manifest). The AST
/// is intentionally not serialized; see the module docstring for the
/// `SyntaxContext`/`Globals` rationale.
pub fn write_stage_one_sidecars(
    report_out_dir: &Path,
    chunk_id: &str,
    stage_one: &StageOneAnalysis,
) -> Result<()> {
    let dir = chunk_analysis_dir(report_out_dir, chunk_id);
    fs::create_dir_all(&dir)
        .with_context(|| format!("create chunk_analysis dir: {}", dir.display()))?;

    let facts = ChunkFactsReport::from_analysis(&stage_one.fact_analysis);
    write_pretty_json(&dir.join(CHUNK_ANALYSIS_FACTS_REPORT), &facts)
        .with_context(|| format!("write {CHUNK_ANALYSIS_FACTS_REPORT}"))?;

    write_pretty_json(
        &dir.join(CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT),
        &stage_one.owner_graph_and_units.atomic_units,
    )
    .with_context(|| format!("write {CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT}"))?;

    let manifest = ChunkAnalysisManifest::new(chunk_id);
    write_pretty_json(&dir.join(CHUNK_ANALYSIS_MANIFEST_REPORT), &manifest)
        .with_context(|| format!("write {CHUNK_ANALYSIS_MANIFEST_REPORT}"))?;

    Ok(())
}

fn chunk_analysis_dir(report_out_dir: &Path, chunk_id: &str) -> PathBuf {
    report_out_dir
        .join(chunk_id.split('/').collect::<PathBuf>())
        .join(CHUNK_ANALYSIS_DIR)
}

fn write_pretty_json<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let body = serde_json::to_string_pretty(value)?;
    fs::write(path, body).with_context(|| format!("write {}", path.display()))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AnalysisHints;
    use crate::compute_stage_one_analysis;
    use crate::graph::OwnerGraphOptions;
    use swc_common::{FileName, SourceMap, sync::Lrc};
    use swc_ecma_ast::Module;
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    fn parse(source: &str) -> Module {
        let cm: Lrc<SourceMap> = Default::default();
        let fm = cm.new_source_file(
            FileName::Custom("test.js".into()).into(),
            source.to_string(),
        );
        let lexer = Lexer::new(
            Syntax::Es(Default::default()),
            Default::default(),
            StringInput::from(&*fm),
            None,
        );
        Parser::new_from(lexer)
            .parse_module()
            .expect("parse module")
    }

    #[test]
    fn writes_v1_sidecars_under_chunk_analysis_dir() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let module = parse("const A = 1;\nconst B = A + 1;\nexport { A, B };\n");
        let stage_one = compute_stage_one_analysis(
            &module,
            &AnalysisHints::default(),
            None,
            |_| None,
            OwnerGraphOptions::default(),
        );

        write_stage_one_sidecars(tmp.path(), "static/app", &stage_one).expect("write sidecars");

        let dir = tmp.path().join("static/app/chunk_analysis");
        assert!(dir.is_dir(), "chunk_analysis dir created: {}", dir.display());
        for name in [
            CHUNK_ANALYSIS_FACTS_REPORT,
            CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT,
            CHUNK_ANALYSIS_MANIFEST_REPORT,
        ] {
            assert!(
                dir.join(name).is_file(),
                "{name} written under {}",
                dir.display(),
            );
        }

        // ast.json is intentionally NOT written; see module docstring.
        assert!(
            !dir.join("ast.json").exists(),
            "ast.json must not be written in v1 (see module docstring)",
        );

        let manifest_body =
            fs::read_to_string(dir.join(CHUNK_ANALYSIS_MANIFEST_REPORT)).expect("read manifest");
        let manifest: ChunkAnalysisManifest =
            serde_json::from_str(&manifest_body).expect("parse manifest");
        assert_eq!(manifest.schema_version, CHUNK_ANALYSIS_MANIFEST_SCHEMA_VERSION);
        assert_eq!(manifest.chunk_id, "static/app");
        assert_eq!(manifest.paths.len(), 2);
    }
}
