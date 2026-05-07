use std::fs;
use std::path::Path;

use anyhow::{Result, bail};
use serde::Serialize;

use artifact::{
    JsPipelineArtifact, list_chunk_file_paths, manifest_relative_path, materialize_artifact_scripts,
};
use scrambled_id_frequencies::{compute_scrambled_identifier_frequencies, write_queue};

#[derive(Debug, Clone)]
pub struct WriteJsTreeManifest {
    /// Always `"."` — the manifest sits at `<out_dir>/manifest.json`, so
    /// `out_dir` is the manifest's own directory. Recorded explicitly so
    /// downstream readers can confirm the manifest's role.
    pub out_dir: String,
    pub counts: WriteJsTreeCounts,
    pub files: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct WriteJsTreeCounts {
    pub chunks: usize,
    pub files: usize,
}

pub fn write_js_tree(
    artifact: &JsPipelineArtifact,
    out_dir: &Path,
    force: bool,
) -> Result<WriteJsTreeManifest> {
    if out_dir.as_os_str().is_empty() {
        bail!("write_js_tree requires out_dir");
    }
    prepare_output_dir(out_dir, force)?;

    let chunk_ids = artifact.list_chunk_ids();
    let files = chunk_ids
        .iter()
        .map(|chunk_id| {
            let chunk = artifact.js_chunk(chunk_id)?;
            Ok(list_chunk_file_paths(chunk)
                .into_iter()
                .map(|file_path| format!("{chunk_id}/{file_path}"))
                .collect::<Vec<_>>())
        })
        .collect::<Result<Vec<_>>>()?
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    let output_metrics = materialize_artifact_scripts(artifact, out_dir)?;

    // The scrambled-identifier frequency queue is a side output of every
    // pipeline run that writes a tree manifest. Emit it now and record
    // its manifest-relative path on the root manifest.
    let queue = compute_scrambled_identifier_frequencies(artifact)?;
    let queue_path = write_queue(out_dir, &queue)?;
    let manifest_path = out_dir.join("manifest.json");
    let mut root_manifest = artifact.root_manifest.clone();
    root_manifest.scrambled_identifier_frequencies =
        Some(manifest_relative_path(&manifest_path, &queue_path));
    root_manifest.output_metrics = Some(output_metrics.clone());
    fs::write(
        &manifest_path,
        serde_json::to_string_pretty(&root_manifest)? + "\n",
    )?;
    fs::write(
        out_dir.join("package.json"),
        serde_json::to_string_pretty(&PackageManifest {
            module_type: "module",
        })? + "\n",
    )?;

    Ok(WriteJsTreeManifest {
        out_dir: ".".to_string(),
        counts: WriteJsTreeCounts {
            chunks: chunk_ids.len(),
            files: files.len(),
        },
        files,
    })
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
