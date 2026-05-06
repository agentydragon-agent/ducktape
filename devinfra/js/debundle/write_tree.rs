use std::fs;
use std::path::Path;

use anyhow::{Context, Result, bail};
use serde::Serialize;

use artifact::{
    FileRole, JsPipelineArtifact, OutputFileMetric, OutputFraction, OutputMetrics, OutputRole,
    OutputSize, SelectedModuleLowering, list_chunk_file_paths, manifest_relative_path,
    path_from_module_path,
};
use js_ast::emit_js_module;
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
    let mut files = Vec::new();
    let mut output_metrics = OutputMetricsBuilder::default();
    let selected_module_by_chunk_file = selected_module_by_chunk_file(artifact);
    let mut chunk_metrics = chunk_ids
        .iter()
        .cloned()
        .map(|chunk_id| (chunk_id, OutputMetricsBuilder::default()))
        .collect::<std::collections::BTreeMap<_, _>>();
    for chunk_id in &chunk_ids {
        let chunk = artifact
            .chunks
            .get(chunk_id)
            .with_context(|| format!("missing artifact chunk {chunk_id}"))?;
        for file_path in list_chunk_file_paths(chunk) {
            let file = chunk
                .files
                .get(&file_path)
                .with_context(|| format!("missing artifact file {chunk_id}/{file_path}"))?;
            let ast = file
                .ast
                .as_ref()
                .with_context(|| format!("artifact file has no AST: {chunk_id}/{file_path}"))?;
            let output_path = out_dir
                .join(path_from_module_path(chunk_id))
                .join(path_from_module_path(&file_path));
            if let Some(parent) = output_path.parent() {
                fs::create_dir_all(parent)?;
            }
            let rendered = emit_js_module(ast, &file.header_lines)?;
            let metric = file_metric(
                chunk_id,
                &file_path,
                &rendered,
                &selected_module_by_chunk_file,
                file.metadata.role,
            );
            fs::write(output_path, rendered)?;
            output_metrics.add_file(metric.clone());
            let mut chunk_metric = metric.clone();
            chunk_metric.file = file_path.clone();
            chunk_metrics
                .get_mut(chunk_id)
                .expect("chunk metrics initialized")
                .add_file(chunk_metric);
            files.push(format!("{chunk_id}/{file_path}"));
        }
    }
    let output_metrics = output_metrics.finish();

    // The scrambled-identifier frequency queue is a side output of every
    // pipeline run that writes a tree manifest. Emit it now and record
    // its manifest-relative path on the root manifest.
    let queue = compute_scrambled_identifier_frequencies(artifact)?;
    let queue_path = write_queue(out_dir, &queue)?;
    if let Some(root_manifest) = &artifact.root_manifest {
        let manifest_path = out_dir.join("manifest.json");
        let mut root_manifest = root_manifest.clone();
        root_manifest.scrambled_identifier_frequencies =
            Some(manifest_relative_path(&manifest_path, &queue_path));
        root_manifest.output_metrics = Some(output_metrics.clone());
        fs::write(
            &manifest_path,
            serde_json::to_string_pretty(&root_manifest)? + "\n",
        )?;
    }
    for chunk_id in &chunk_ids {
        if let Some(manifest) = artifact.chunk_manifests.get(chunk_id) {
            let mut manifest = manifest.clone();
            manifest.output_metrics = Some(
                chunk_metrics
                    .remove(chunk_id)
                    .expect("chunk metrics initialized")
                    .finish(),
            );
            let manifest_path = out_dir
                .join(path_from_module_path(chunk_id))
                .join("manifest.json");
            if let Some(parent) = manifest_path.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(
                manifest_path,
                serde_json::to_string_pretty(&manifest)? + "\n",
            )?;
        }
    }
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

#[derive(Default)]
struct OutputMetricsBuilder {
    total: OutputSize,
    top_level_entry: OutputSize,
    named_modules: OutputSize,
    residual_modules: OutputSize,
    other_files: OutputSize,
    largest_files_by_bytes: Vec<OutputFileMetric>,
}

impl OutputMetricsBuilder {
    fn add_file(&mut self, metric: OutputFileMetric) {
        let size = OutputSize {
            files: 1,
            bytes: metric.bytes,
            lines: metric.lines,
        };
        add_output_size(&mut self.total, &size);
        match metric.role {
            OutputRole::TopLevelEntry => add_output_size(&mut self.top_level_entry, &size),
            OutputRole::NamedModule => add_output_size(&mut self.named_modules, &size),
            OutputRole::ResidualModule => add_output_size(&mut self.residual_modules, &size),
            OutputRole::Other => add_output_size(&mut self.other_files, &size),
        }
        self.largest_files_by_bytes.push(metric);
    }

    fn finish(mut self) -> OutputMetrics {
        self.largest_files_by_bytes.sort_by(|left, right| {
            right
                .bytes
                .cmp(&left.bytes)
                .then_with(|| left.file.cmp(&right.file))
        });
        self.largest_files_by_bytes.truncate(20);
        OutputMetrics {
            named_module_fraction: output_fraction(&self.named_modules, &self.total),
            residual_module_fraction: output_fraction(&self.residual_modules, &self.total),
            top_level_entry_fraction: output_fraction(&self.top_level_entry, &self.total),
            total: self.total,
            top_level_entry: self.top_level_entry,
            named_modules: self.named_modules,
            residual_modules: self.residual_modules,
            other_files: self.other_files,
            largest_files_by_bytes: self.largest_files_by_bytes,
        }
    }
}

fn selected_module_by_chunk_file(
    artifact: &JsPipelineArtifact,
) -> std::collections::BTreeMap<(String, String), SelectedModuleLowering> {
    artifact
        .chunk_manifests
        .values()
        .flat_map(|manifest| manifest.selected_module_lowerings.iter().flatten())
        .map(|lowering| {
            (
                (lowering.chunk_id.clone(), lowering.target_file.clone()),
                lowering.clone(),
            )
        })
        .collect()
}

fn file_metric(
    chunk_id: &str,
    file_path: &str,
    rendered: &str,
    selected_module_by_chunk_file: &std::collections::BTreeMap<
        (String, String),
        SelectedModuleLowering,
    >,
    role: Option<FileRole>,
) -> OutputFileMetric {
    let lowering =
        selected_module_by_chunk_file.get(&(chunk_id.to_string(), file_path.to_string()));
    let role = if let Some(lowering) = lowering {
        if lowering.residual {
            OutputRole::ResidualModule
        } else {
            OutputRole::NamedModule
        }
    } else {
        match role {
            Some(FileRole::Entry) => OutputRole::TopLevelEntry,
            Some(FileRole::Module) => OutputRole::NamedModule,
            Some(FileRole::Runtime) | None => OutputRole::Other,
        }
    };
    OutputFileMetric {
        file: format!("{chunk_id}/{file_path}"),
        role,
        bytes: rendered.len(),
        lines: rendered.lines().count(),
        module_id: lowering.map(|lowering| lowering.id.clone()),
        module_path: lowering.map(|lowering| lowering.target_path.clone()),
    }
}

fn add_output_size(total: &mut OutputSize, part: &OutputSize) {
    total.files += part.files;
    total.bytes += part.bytes;
    total.lines += part.lines;
}

fn output_fraction(part: &OutputSize, total: &OutputSize) -> OutputFraction {
    OutputFraction {
        bytes: fraction(part.bytes, total.bytes),
        lines: fraction(part.lines, total.lines),
    }
}

fn fraction(part: usize, total: usize) -> f64 {
    if total == 0 {
        0.0
    } else {
        part as f64 / total as f64
    }
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
