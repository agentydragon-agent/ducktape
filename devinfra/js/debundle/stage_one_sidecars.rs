//! On-disk sidecar writers for Stage A artifacts.
//!
//! Stage A (see `stage_one.rs` and DESIGN.md §"Pipeline split (Stage A /
//! Stage B)") is the spec-independent half of the per-chunk pipeline.
//! Its output — per-statement facts, the owner graph, and the
//! structural atomic units, plus the AST that produced them — is
//! everything Stage B needs to start. Serializing those values as a
//! collection of sibling JSON files under
//! `reports/tree/<chunk_id>/chunk_analysis/` gives a future
//! `materialize_from_analysis` reader (task #78) a stable read surface,
//! and lets a Bazel rule split the chunk pipeline into two cacheable
//! actions.
//!
//! ## File layout
//!
//! Given `report_out_dir = <reports>/tree` (the layout's tree root —
//! the same value `write_chunk_report_json` already receives), this
//! writer creates a `<chunk_id>/chunk_analysis/` directory holding
//! four sibling files:
//!
//! - `ast.json`        — the raw `swc_ecma_ast::Module` (swc's
//!   `serde-impl` feature handles serialization end-to-end).
//! - `facts.json`      — a `ChunkFactsReport` (see `facts/wire.rs`)
//!   round-trippable back into `ChunkFactAnalysis`.
//! - `atomic_units.json` — the `Vec<AtomicUnit>` from
//!   `OwnerGraphAndUnits` (already `Serialize`).
//! - `manifest.json`   — a small envelope with `schema_version`,
//!   `chunk_id`, and the sibling filenames a reader should expect.
//!
//! Each file is written pretty-printed; together they're small (the
//! AST and facts dominate, and they're capped by chunk size).
//!
//! ## Why a manifest
//!
//! The manifest pins the on-disk filenames and a `schema_version` so a
//! reader can fail fast on shape drift without probing for every
//! sibling file. The `paths` array intentionally lists the four
//! companion filenames (not absolute paths) so the artifact is
//! relocatable — a reader resolves them relative to the manifest's
//! parent directory.

use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use swc_ecma_ast::Module;

use output_layout::{
    CHUNK_ANALYSIS_AST_REPORT, CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT, CHUNK_ANALYSIS_DIR,
    CHUNK_ANALYSIS_FACTS_REPORT, CHUNK_ANALYSIS_MANIFEST_REPORT,
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
                CHUNK_ANALYSIS_AST_REPORT.to_string(),
                CHUNK_ANALYSIS_FACTS_REPORT.to_string(),
                CHUNK_ANALYSIS_ATOMIC_UNITS_REPORT.to_string(),
            ],
        }
    }
}

/// Write all four Stage A sidecars to
/// `<report_out_dir>/<chunk_id>/chunk_analysis/`.
///
/// `report_out_dir` is the *tree root* (the same path `materialize_*`
/// passes to `write_chunk_report_json`). The `chunk_id` is interpreted
/// as a `/`-separated subpath so chunk ids like `static/app` nest
/// correctly under the tree root — matching the convention every
/// other chunk-report writer in the crate uses.
pub fn write_stage_one_sidecars(
    report_out_dir: &Path,
    chunk_id: &str,
    stage_one: &StageOneAnalysis,
    module: &Module,
) -> Result<()> {
    let dir = chunk_analysis_dir(report_out_dir, chunk_id);
    fs::create_dir_all(&dir)
        .with_context(|| format!("create chunk_analysis dir: {}", dir.display()))?;

    write_pretty_json(&dir.join(CHUNK_ANALYSIS_AST_REPORT), module)
        .with_context(|| format!("write {CHUNK_ANALYSIS_AST_REPORT}"))?;

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
    fn writes_four_sidecars_under_chunk_analysis_dir() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let module = parse("const A = 1;\nconst B = A + 1;\nexport { A, B };\n");
        let stage_one = compute_stage_one_analysis(
            &module,
            &AnalysisHints::default(),
            None,
            |_| None,
            OwnerGraphOptions::default(),
        );

        write_stage_one_sidecars(tmp.path(), "static/app", &stage_one, &module)
            .expect("write sidecars");

        let dir = tmp.path().join("static/app/chunk_analysis");
        assert!(dir.is_dir(), "chunk_analysis dir created: {}", dir.display());
        for name in [
            CHUNK_ANALYSIS_AST_REPORT,
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

        let manifest_body = fs::read_to_string(dir.join(CHUNK_ANALYSIS_MANIFEST_REPORT))
            .expect("read manifest");
        let manifest: ChunkAnalysisManifest =
            serde_json::from_str(&manifest_body).expect("parse manifest");
        assert_eq!(manifest.schema_version, CHUNK_ANALYSIS_MANIFEST_SCHEMA_VERSION);
        assert_eq!(manifest.chunk_id, "static/app");
        assert_eq!(manifest.paths.len(), 3);
    }
}
