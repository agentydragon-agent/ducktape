use std::collections::HashMap;
use std::fs;
use std::path::Path;

use anyhow::{Result, bail};
use serde::Serialize;

use artifact::{
    ArtifactChunkRecord, ArtifactCounts, ArtifactManifest, ChunkBundle, ChunkDecompositionOutput,
    ChunkId, DecompositionMetrics, RootLogicalModulesSummary, SelectedModuleLowering,
    manifest_relative_path, materialize_artifact_scripts,
};
use identifier_rename_queue::{compute_identifier_rename_queue, write_queue};

pub struct WriteTreeInput<'a> {
    pub artifact: &'a ChunkBundle,
    pub out_dir: &'a Path,
    pub force: bool,
    pub lowerings: &'a [SelectedModuleLowering],
    pub counts: &'a ArtifactCounts,
    pub chunk_records: &'a [ArtifactChunkRecord],
    pub module_count: usize,
    pub decomposition_by_chunk: &'a HashMap<ChunkId, ChunkDecompositionOutput>,
}

pub fn write_js_tree(input: &WriteTreeInput) -> Result<()> {
    if input.out_dir.as_os_str().is_empty() {
        bail!("write_js_tree requires out_dir");
    }
    prepare_output_dir(input.out_dir, input.force)?;

    let materialized =
        materialize_artifact_scripts(input.artifact, input.out_dir, input.decomposition_by_chunk)?;

    let decomposition_metrics = if input.lowerings.is_empty() {
        None
    } else {
        Some(DecompositionMetrics::compute(
            input.lowerings,
            &materialized.file_metrics,
        ))
    };

    let queue = compute_identifier_rename_queue(input.artifact, input.decomposition_by_chunk)?;
    let queue_path = write_queue(input.out_dir, &queue)?;
    let manifest_path = input.out_dir.join("manifest.json");
    let manifest = ArtifactManifest {
        counts: input.counts.clone(),
        chunks: input.chunk_records.to_vec(),
        logical_modules: RootLogicalModulesSummary {
            module_count: input.module_count,
        },
        selected_module_lowerings: input.lowerings.to_vec(),
        identifier_rename_queue: manifest_relative_path(&manifest_path, &queue_path),
        output_metrics: materialized.output_metrics,
        decomposition_metrics,
    };
    serde_json::to_writer_pretty(&fs::File::create(&manifest_path)?, &manifest)?;
    serde_json::to_writer_pretty(
        &fs::File::create(input.out_dir.join("package.json"))?,
        &PackageManifest {
            module_type: "module",
        },
    )?;

    Ok(())
}

#[derive(Serialize)]
struct PackageManifest {
    #[serde(rename = "type")]
    module_type: &'static str,
}

fn prepare_output_dir(out_dir: &Path, force: bool) -> Result<()> {
    if out_dir.exists() {
        let metadata = fs::metadata(out_dir)?;
        if !metadata.is_dir() {
            bail!(
                "Output path exists and is not a directory: {}",
                out_dir.display()
            );
        }
        if fs::read_dir(out_dir)?.next().is_some() && !force {
            bail!(
                "Output directory is not empty: {}. Pass --force to replace it.",
                out_dir.display()
            );
        }
        if force {
            fs::remove_dir_all(out_dir)?;
        }
    }
    fs::create_dir_all(out_dir)?;
    Ok(())
}
