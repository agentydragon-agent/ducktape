use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use relative_path::RelativePath;
use serde::Serialize;

use js_ast::{ParsedJsModule, emit_js_module, parse_js_module};

pub const CANONICAL_CHUNK_ENTRY_FILE: &str = "entry.js";

#[derive(Default)]
pub struct JsPipelineArtifact {
    pub chunk_order: Vec<String>,
    pub chunks: BTreeMap<String, JsChunk>,
    pub root_manifest: Option<ArtifactManifest>,
    pub chunk_manifests: BTreeMap<String, ChunkManifest>,
}

pub struct JsChunk {
    pub entry_file: String,
    pub files: BTreeMap<String, JsFile>,
    pub metadata: ChunkMetadata,
}

pub struct JsFile {
    pub path: String,
    pub content: Option<String>,
    pub ast: Option<ParsedJsModule>,
    pub header_lines: Vec<String>,
    pub metadata: FileMetadata,
}

#[derive(Debug, Clone, Default)]
#[allow(dead_code)]
pub struct ChunkMetadata {
    pub source_path: Option<String>,
    pub module_extraction_state: Option<ModuleExtractionState>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModuleExtractionState {
    pub runtime_file: String,
    pub target_dir: String,
}

#[derive(Debug, Clone, Default)]
pub struct FileMetadata {
    pub chunk_id: Option<String>,
    pub chunk_file: Option<String>,
    pub role: Option<FileRole>,
    pub source_path: Option<String>,
    pub generated_stage: Option<String>,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FileRole {
    Entry,
    Module,
    Runtime,
}

#[derive(Debug, Clone, Serialize)]
pub struct LoadedJsChunksManifest {
    pub counts: LoadedCounts,
    pub chunks: Vec<LoadedChunkRecord>,
    pub js_files: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct LoadedCounts {
    pub chunks: usize,
    pub files: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct LoadedChunkRecord {
    pub chunk_id: String,
    pub entry_file: String,
    pub source_path: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ComputeJsAstsManifest {
    pub counts: ComputeJsAstsCounts,
}

#[derive(Debug, Clone, Serialize)]
pub struct ComputeJsAstsCounts {
    pub parsed: usize,
    pub files: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactManifest {
    pub counts: ArtifactCounts,
    pub chunks: Vec<ArtifactChunkRecord>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub logical_modules: Option<RootLogicalModulesSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_module_lowerings: Option<Vec<SelectedModuleLowering>>,
    /// Path (manifest-relative) to the scrambled-identifier frequency
    /// queue side output, when this manifest was produced by a stage
    /// that emits to a writable directory (e.g. `write_js_tree`).
    /// `None` for early-pipeline manifests that never see a final
    /// output directory.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scrambled_identifier_frequencies: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_metrics: Option<OutputMetrics>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactCounts {
    pub chunks: usize,
    pub kept_top_level_declaration_owners: usize,
    pub top_level_side_effects: usize,
    pub export_aliases: usize,
    pub unresolved_exports: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_module_lowerings: Option<usize>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RootLogicalModulesSummary {
    pub module_count: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkLogicalModulesSummary {
    pub count: usize,
    pub module_ids: Vec<String>,
    pub target_dir: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SelectedModuleLowering {
    pub binding_names: Vec<String>,
    pub chunk_id: String,
    pub exported_names: Vec<String>,
    pub file: String,
    pub id: String,
    pub owner_ids: Vec<String>,
    pub residual: bool,
    pub target_file: String,
    pub target_path: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactChunkRecord {
    pub chunk_id: String,
    pub source_path: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkManifest {
    pub chunk_id: String,
    pub source_path: String,
    pub parser: ParserOptionsRecord,
    pub entry_file: String,
    pub counts: ChunkCounts,
    pub files: Vec<ChunkFileRecord>,
    pub imports: Vec<ImportRecord>,
    pub export_aliases: Vec<ExportAliasRecord>,
    pub unresolved_exports: Vec<ExportAliasRecord>,
    pub kept_top_level_declarations: Vec<KeptTopLevelDeclarationRecord>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub logical_modules: Option<ChunkLogicalModulesSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_module_lowerings: Option<Vec<SelectedModuleLowering>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_metrics: Option<OutputMetrics>,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutputMetrics {
    pub total: OutputSize,
    pub top_level_entry: OutputSize,
    pub named_modules: OutputSize,
    pub residual_modules: OutputSize,
    pub other_files: OutputSize,
    pub named_module_fraction: OutputFraction,
    pub residual_module_fraction: OutputFraction,
    pub top_level_entry_fraction: OutputFraction,
    pub largest_files_by_bytes: Vec<OutputFileMetric>,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct OutputSize {
    pub files: usize,
    pub bytes: usize,
    pub lines: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutputFraction {
    pub bytes: f64,
    pub lines: f64,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputRole {
    TopLevelEntry,
    NamedModule,
    ResidualModule,
    Other,
}

#[derive(Debug, Clone, Serialize)]
pub struct OutputFileMetric {
    pub file: String,
    pub role: OutputRole,
    pub bytes: usize,
    pub lines: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub module_path: Option<String>,
}

impl OutputMetrics {
    fn from_file_metrics(metrics: impl IntoIterator<Item = OutputFileMetric>) -> Self {
        let metrics = metrics.into_iter().collect::<Vec<_>>();
        let total = OutputSize::sum(metrics.iter());
        let top_level_entry = size_for_role(&metrics, OutputRole::TopLevelEntry);
        let named_modules = size_for_role(&metrics, OutputRole::NamedModule);
        let residual_modules = size_for_role(&metrics, OutputRole::ResidualModule);
        let other_files = size_for_role(&metrics, OutputRole::Other);
        OutputMetrics {
            named_module_fraction: output_fraction(&named_modules, &total),
            residual_module_fraction: output_fraction(&residual_modules, &total),
            top_level_entry_fraction: output_fraction(&top_level_entry, &total),
            total,
            top_level_entry,
            named_modules,
            residual_modules,
            other_files,
            largest_files_by_bytes: largest_files_by_bytes(metrics),
        }
    }
}

impl OutputSize {
    fn from_file(file: &OutputFileMetric) -> Self {
        Self {
            files: 1,
            bytes: file.bytes,
            lines: file.lines,
        }
    }

    fn sum<'a>(files: impl IntoIterator<Item = &'a OutputFileMetric>) -> Self {
        files
            .into_iter()
            .map(Self::from_file)
            .fold(Self::default(), |left, right| Self {
                files: left.files + right.files,
                bytes: left.bytes + right.bytes,
                lines: left.lines + right.lines,
            })
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ParserOptionsRecord {
    pub allow_undeclared_exports: bool,
    pub plugins: Vec<&'static str>,
    pub source_type: &'static str,
}

impl Default for ParserOptionsRecord {
    fn default() -> Self {
        Self {
            allow_undeclared_exports: true,
            plugins: vec!["jsx", "typescript", "importAssertions", "topLevelAwait"],
            source_type: "module",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkCounts {
    pub dynamic_imports: usize,
    pub export_aliases: usize,
    pub import_declarations: usize,
    pub kept_top_level_declaration_owners: usize,
    pub top_level_bindings: usize,
    pub top_level_declaration_owners: usize,
    pub top_level_side_effects: usize,
    pub unresolved_exports: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChunkFileRecord {
    pub file: String,
    pub role: FileRole,
}

#[derive(Debug, Clone, Serialize)]
pub struct ImportRecord {
    pub id: String,
    pub line: Option<usize>,
    pub source: String,
    pub specifiers: Vec<ImportSpecifierRecord>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ImportSpecifierRecord {
    pub kind: ImportSpecifierKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub imported: Option<String>,
    pub local: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ImportSpecifierKind {
    Named,
    Default,
    Namespace,
}

#[derive(Debug, Clone, Serialize)]
pub struct ExportAliasRecord {
    pub exported: String,
    pub line: Option<usize>,
    pub local: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct KeptTopLevelDeclarationRecord {
    pub id: String,
    pub line: Option<usize>,
    pub names: Vec<String>,
    pub kind: TopLevelDeclarationKind,
    pub unsafe_reason: &'static str,
}

/// The three top-level declaration variants we anchor extraction on.
/// Mirrors the SWC `Decl` arms where `analyze_program_shallow` produces
/// an `OwnerRecord`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TopLevelDeclarationKind {
    Function,
    Class,
    Variable,
}

impl JsPipelineArtifact {
    pub fn list_chunk_ids(&self) -> Vec<String> {
        if self.chunk_order.is_empty() {
            self.chunks.keys().cloned().collect()
        } else {
            self.chunk_order.clone()
        }
    }

    pub fn list_js_file_keys(&self) -> Vec<(String, String)> {
        self.list_chunk_ids()
            .into_iter()
            .flat_map(|chunk_id| {
                self.chunks
                    .get(&chunk_id)
                    .map(|chunk| {
                        chunk
                            .files
                            .keys()
                            .map(|file| (chunk_id.clone(), file.clone()))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default()
            })
            .collect()
    }

    pub fn chunk_source_path(&self, chunk_id: &str) -> Option<String> {
        self.chunk_manifests
            .get(chunk_id)
            .map(|manifest| manifest.source_path.clone())
            .or_else(|| {
                self.chunks
                    .get(chunk_id)
                    .and_then(|chunk| chunk.metadata.source_path.clone())
            })
            .or_else(|| Some(format!("{chunk_id}.js")))
    }

    pub fn source_chunk_index(&self) -> Result<BTreeMap<String, String>> {
        let mut out = BTreeMap::new();
        for chunk_id in self.list_chunk_ids() {
            let Some(source_path) = self.chunk_source_path(&chunk_id) else {
                continue;
            };
            if let Some(existing) = out.insert(source_path.clone(), chunk_id.clone()) {
                bail!("Duplicate chunk sourcePath {source_path}: {existing} and {chunk_id}");
            }
        }
        Ok(out)
    }
}

pub fn load_js_chunks(
    input_root: &Path,
    js_list_path: &Path,
) -> Result<(JsPipelineArtifact, LoadedJsChunksManifest)> {
    let js_files = parse_js_list(
        &fs::read_to_string(js_list_path)
            .with_context(|| format!("reading {}", js_list_path.display()))?,
    )?;
    let mut artifact = JsPipelineArtifact::default();
    for source_path in &js_files {
        let absolute_path = input_root.join(source_path);
        let entry_file = Path::new(source_path)
            .file_name()
            .and_then(|value| value.to_str())
            .context("source path missing file name")?
            .to_string();
        let chunk_id = chunk_id_for_js_path(source_path)?;
        let content = fs::read_to_string(&absolute_path)
            .with_context(|| format!("reading {}", absolute_path.display()))?;
        let mut files = BTreeMap::new();
        files.insert(
            entry_file.clone(),
            JsFile {
                path: entry_file.clone(),
                content: Some(content),
                ast: None,
                header_lines: Vec::new(),
                metadata: FileMetadata {
                    chunk_id: Some(chunk_id.clone()),
                    chunk_file: Some(entry_file.clone()),
                    role: Some(FileRole::Entry),
                    source_path: Some(source_path.clone()),
                    ..Default::default()
                },
            },
        );
        artifact.chunk_order.push(chunk_id.clone());
        artifact.chunks.insert(
            chunk_id.clone(),
            JsChunk {
                entry_file,
                files,
                metadata: ChunkMetadata {
                    source_path: Some(source_path.clone()),
                    module_extraction_state: None,
                },
            },
        );
    }
    let manifest = LoadedJsChunksManifest {
        counts: LoadedCounts {
            chunks: js_files.len(),
            files: js_files.len(),
        },
        chunks: js_files
            .iter()
            .map(|source_path| {
                Ok(LoadedChunkRecord {
                    chunk_id: chunk_id_for_js_path(source_path)?,
                    entry_file: Path::new(source_path)
                        .file_name()
                        .and_then(|value| value.to_str())
                        .context("source path missing file name")?
                        .to_string(),
                    source_path: source_path.clone(),
                })
            })
            .collect::<Result<Vec<_>>>()?,
        js_files,
    };
    Ok((artifact, manifest))
}

pub fn compute_js_asts(
    artifact: &mut JsPipelineArtifact,
    drop_content: bool,
) -> Result<ComputeJsAstsManifest> {
    let keys = artifact.list_js_file_keys();
    let mut parsed = 0usize;
    for (chunk_id, file_path) in &keys {
        let chunk = artifact
            .chunks
            .get_mut(chunk_id)
            .with_context(|| format!("missing artifact chunk {chunk_id}"))?;
        let file = chunk
            .files
            .get_mut(file_path)
            .with_context(|| format!("missing artifact file {chunk_id}/{file_path}"))?;
        if file.ast.is_some() {
            continue;
        }
        let content = file
            .content
            .as_deref()
            .with_context(|| format!("computeJsAsts requires content for file: {}", file.path))?;
        file.ast = Some(parse_js_module(
            &format!("{chunk_id}/{file_path}"),
            content,
        )?);
        if drop_content {
            file.content = None;
        }
        parsed += 1;
    }
    Ok(ComputeJsAstsManifest {
        counts: ComputeJsAstsCounts {
            parsed,
            files: keys.len(),
        },
    })
}

pub fn materialize_artifact_scripts(
    artifact: &JsPipelineArtifact,
    out_dir: &Path,
) -> Result<OutputMetrics> {
    let selected_module_by_chunk_file = selected_module_by_chunk_file(artifact);
    let metrics = artifact
        .list_chunk_ids()
        .into_iter()
        .map(|chunk_id| {
            materialize_chunk_scripts(artifact, out_dir, &selected_module_by_chunk_file, chunk_id)
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(OutputMetrics::from_file_metrics(
        metrics.into_iter().flatten(),
    ))
}

fn materialize_chunk_scripts(
    artifact: &JsPipelineArtifact,
    out_dir: &Path,
    selected_module_by_chunk_file: &BTreeMap<(String, String), &SelectedModuleLowering>,
    chunk_id: String,
) -> Result<Vec<OutputFileMetric>> {
    let chunk = artifact
        .chunks
        .get(&chunk_id)
        .with_context(|| format!("missing artifact chunk {chunk_id}"))?;
    let chunk_out_dir = out_dir.join(path_from_module_path(&chunk_id));
    fs::create_dir_all(&chunk_out_dir)?;
    let metrics = list_chunk_file_paths(chunk)
        .into_iter()
        .map(|file| {
            materialize_chunk_file(
                chunk,
                &chunk_id,
                &chunk_out_dir,
                selected_module_by_chunk_file,
                file,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    if let Some(manifest) = artifact.chunk_manifests.get(&chunk_id) {
        let mut manifest = manifest.clone();
        manifest.output_metrics = Some(OutputMetrics::from_file_metrics(
            metrics
                .iter()
                .map(|metric| chunk_relative_metric(&chunk_id, metric)),
        ));
        fs::write(
            chunk_out_dir.join("manifest.json"),
            serde_json::to_string_pretty(&manifest)? + "\n",
        )?;
    }
    Ok(metrics)
}

fn materialize_chunk_file(
    chunk: &JsChunk,
    chunk_id: &str,
    chunk_out_dir: &Path,
    selected_module_by_chunk_file: &BTreeMap<(String, String), &SelectedModuleLowering>,
    file: String,
) -> Result<OutputFileMetric> {
    let file_artifact = chunk
        .files
        .get(&file)
        .with_context(|| format!("missing artifact file {chunk_id}/{file}"))?;
    let ast = file_artifact
        .ast
        .as_ref()
        .with_context(|| format!("artifact file has no AST: {chunk_id}/{file}"))?;
    let target_path = chunk_out_dir.join(path_from_module_path(&file));
    if let Some(parent) = target_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let rendered = emit_js_module(ast, &file_artifact.header_lines)?;
    let metric = output_file_metric(
        chunk_id,
        &file,
        &rendered,
        selected_module_by_chunk_file,
        file_artifact.metadata.role,
    )?;
    fs::write(&target_path, rendered)?;
    Ok(metric)
}

fn chunk_relative_metric(chunk_id: &str, metric: &OutputFileMetric) -> OutputFileMetric {
    let prefix = format!("{chunk_id}/");
    OutputFileMetric {
        file: metric
            .file
            .strip_prefix(&prefix)
            .unwrap_or(&metric.file)
            .to_string(),
        ..metric.clone()
    }
}

fn selected_module_by_chunk_file(
    artifact: &JsPipelineArtifact,
) -> BTreeMap<(String, String), &SelectedModuleLowering> {
    artifact
        .chunk_manifests
        .values()
        .flat_map(|manifest| manifest.selected_module_lowerings.iter().flatten())
        .map(|lowering| {
            (
                (lowering.chunk_id.clone(), lowering.target_file.clone()),
                lowering,
            )
        })
        .collect()
}

fn output_file_metric(
    chunk_id: &str,
    file_path: &str,
    rendered: &str,
    selected_module_by_chunk_file: &BTreeMap<(String, String), &SelectedModuleLowering>,
    role: Option<FileRole>,
) -> Result<OutputFileMetric> {
    let lowering = selected_module_by_chunk_file
        .get(&(chunk_id.to_string(), file_path.to_string()))
        .copied();
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
    Ok(OutputFileMetric {
        file: join_module_path(&[chunk_id, file_path]),
        role,
        bytes: rendered.len(),
        lines: rendered.lines().count(),
        module_id: lowering.map(|lowering| lowering.id.clone()),
        module_path: lowering.map(|lowering| lowering.target_path.clone()),
    })
}

fn output_fraction(part: &OutputSize, total: &OutputSize) -> OutputFraction {
    OutputFraction {
        bytes: fraction(part.bytes, total.bytes),
        lines: fraction(part.lines, total.lines),
    }
}

fn size_for_role(files: &[OutputFileMetric], role: OutputRole) -> OutputSize {
    OutputSize::sum(files.iter().filter(|file| file.role == role))
}

fn largest_files_by_bytes(files: Vec<OutputFileMetric>) -> Vec<OutputFileMetric> {
    let mut sorted = files;
    sorted.sort_by(|left, right| {
        right
            .bytes
            .cmp(&left.bytes)
            .then_with(|| left.file.cmp(&right.file))
    });
    sorted.into_iter().take(20).collect()
}

fn fraction(part: usize, total: usize) -> f64 {
    if total == 0 {
        0.0
    } else {
        part as f64 / total as f64
    }
}

pub fn get_chunk_entry_path(artifact: &JsPipelineArtifact, chunk_id: &str) -> Option<String> {
    let chunk = artifact.chunks.get(chunk_id)?;
    if !chunk.entry_file.is_empty() && chunk.files.contains_key(&chunk.entry_file) {
        return Some(chunk.entry_file.clone());
    }
    artifact
        .chunk_manifests
        .get(chunk_id)
        .and_then(|manifest| {
            chunk
                .files
                .contains_key(&manifest.entry_file)
                .then(|| manifest.entry_file.clone())
        })
        .or_else(|| {
            chunk.files.values().find_map(|file| {
                matches!(
                    file.metadata.role,
                    Some(FileRole::Entry | FileRole::Runtime)
                )
                .then(|| file.path.clone())
            })
        })
        .or_else(|| chunk.files.keys().next().cloned())
}

pub fn resolve_artifact_import_reference(
    artifact: &JsPipelineArtifact,
    source: &str,
    caller_chunk_id: &str,
    caller_file: &str,
) -> Option<(String, String)> {
    if source.is_empty() || !source.starts_with('.') {
        return None;
    }
    let caller_dir =
        join_module_path(&[caller_chunk_id, module_path_dirname(caller_file).as_str()]);
    let resolved_path =
        normalize_module_path(&join_module_path(&[caller_dir.as_str(), source])).ok()?;
    for chunk_id in artifact.list_chunk_ids() {
        let Some(chunk) = artifact.chunks.get(&chunk_id) else {
            continue;
        };
        for file_path in chunk.files.keys() {
            if join_module_path(&[chunk_id.as_str(), file_path.as_str()]) == resolved_path {
                return Some((chunk_id, file_path.clone()));
            }
        }
    }
    None
}

pub fn resolve_artifact_source_import_reference(
    artifact: &JsPipelineArtifact,
    source: &str,
    caller_chunk_id: &str,
    caller_file: &str,
) -> Result<Option<(String, String, String)>> {
    if source.is_empty() || (!source.starts_with('.') && !source.starts_with('/')) {
        return Ok(None);
    }
    let Some(caller_source_path) =
        source_path_for_artifact_file(artifact, caller_chunk_id, caller_file)?
    else {
        return Ok(None);
    };
    let Some(imported_source_path) =
        resolve_chunk_source_path_reference(source, &caller_source_path)
    else {
        return Ok(None);
    };
    let source_index = artifact.source_chunk_index()?;
    let Some(target_chunk_id) = source_index.get(&imported_source_path).cloned() else {
        return Ok(None);
    };
    let Some(target_entry_file) = get_chunk_entry_path(artifact, &target_chunk_id) else {
        return Ok(None);
    };
    let path = join_module_path(&[target_chunk_id.as_str(), target_entry_file.as_str()]);
    Ok(Some((target_chunk_id, target_entry_file, path)))
}

pub fn relative_module_specifier(from_dir: &Path, target_path: &Path) -> String {
    let from = module_path_from_path(from_dir);
    let to = module_path_from_path(target_path);
    let mut specifier = relative_module_path(&from, &to);
    if !specifier.starts_with('.') {
        specifier = format!("./{specifier}");
    }
    specifier
}

pub fn relative_module_path(from_dir: &str, to_path: &str) -> String {
    let relative = RelativePath::new(from_dir)
        .relative(RelativePath::new(to_path))
        .to_string();
    if relative.is_empty() {
        ".".to_string()
    } else {
        relative
    }
}

pub fn chunk_id_for_js_path(js_path: &str) -> Result<String> {
    let normalized = normalize_asset_path(js_path)?;
    Ok(normalized
        .strip_suffix(".js")
        .context("expected normalized .js path")?
        .to_string())
}

pub fn normalize_asset_path(path: &str) -> Result<String> {
    let normalized = normalize_module_path(&path.replace('\\', "/"))?;
    if !normalized.ends_with(".js") {
        bail!("Expected a .js path in JS list: {path}");
    }
    Ok(normalized)
}

pub fn parse_js_list(text: &str) -> Result<Vec<String>> {
    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let normalized = normalize_asset_path(trimmed)?;
        if !seen.insert(normalized.clone()) {
            bail!("JS list contains duplicate paths");
        }
        out.push(normalized);
    }
    Ok(out)
}

pub fn normalize_module_path(value: &str) -> Result<String> {
    if value.is_empty() || value.starts_with('/') {
        bail!("Expected a non-empty relative path");
    }
    let normalized = RelativePath::new(value).normalize();
    if normalized.as_str().is_empty() || normalized.components().any(|part| part.as_str() == "..") {
        bail!("Invalid relative path: {value}");
    }
    Ok(normalized.to_string())
}

pub fn path_from_module_path(path: &str) -> PathBuf {
    RelativePath::new(path).to_path("")
}

pub fn module_path_from_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

/// Render `target` as a path string for inclusion in a manifest serialized at
/// `manifest_path`. If `target` is under `manifest_path`'s parent, the result
/// is relative to that parent (so the manifest tree is portable). Otherwise
/// `target` is returned verbatim. The two paths must share an anchor —
/// either both absolute or both relative to the same cwd; mixing the two
/// produces a degenerate "no common prefix" result and `target` falls
/// through unchanged.
pub fn manifest_relative_path(manifest_path: &Path, target: &Path) -> String {
    let Some(manifest_dir) = manifest_path.parent() else {
        return module_path_from_path(target);
    };
    if let Ok(rel) = target.strip_prefix(manifest_dir) {
        if rel.as_os_str().is_empty() {
            return ".".to_string();
        }
        return module_path_from_path(rel);
    }
    module_path_from_path(target)
}

pub fn join_module_path(parts: &[&str]) -> String {
    parts
        .iter()
        .fold(relative_path::RelativePathBuf::new(), |base, part| {
            base.join_normalized(RelativePath::new(part))
        })
        .to_string()
}

pub fn list_chunk_file_paths(chunk: &JsChunk) -> Vec<String> {
    let mut paths = chunk.files.keys().cloned().collect::<Vec<_>>();
    paths.sort_by(|left, right| {
        if left == &chunk.entry_file {
            std::cmp::Ordering::Less
        } else if right == &chunk.entry_file {
            std::cmp::Ordering::Greater
        } else {
            left.cmp(right)
        }
    });
    paths
}

pub fn module_path_dirname(path: &str) -> String {
    let path = path.replace('\\', "/");
    let normalized = RelativePath::new(&path).normalize();
    normalized
        .parent()
        .map(RelativePath::as_str)
        .unwrap_or("")
        .to_string()
}

fn source_path_for_artifact_file(
    artifact: &JsPipelineArtifact,
    chunk_id: &str,
    file: &str,
) -> Result<Option<String>> {
    let Some(chunk) = artifact.chunks.get(chunk_id) else {
        return Ok(None);
    };
    if let Some(source_path) = chunk
        .files
        .get(file)
        .and_then(|artifact_file| artifact_file.metadata.source_path.clone())
    {
        return Ok(Some(source_path));
    }
    Ok(artifact.chunk_source_path(chunk_id))
}

fn resolve_chunk_source_path_reference(source: &str, caller_source_path: &str) -> Option<String> {
    let imported_path = if source.starts_with('/') {
        normalize_module_path(source.trim_start_matches('/')).ok()?
    } else {
        normalize_module_path(&join_module_path(&[
            module_path_dirname(caller_source_path).as_str(),
            source,
        ]))
        .ok()?
    };
    imported_path.ends_with(".js").then_some(imported_path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn module_path_dirname_normalizes_backslashes() {
        assert_eq!(module_path_dirname("static\\app\\entry.js"), "static/app");
    }

    #[test]
    fn module_path_dirname_normalizes_relative_segments() {
        assert_eq!(module_path_dirname("static/./app/entry.js"), "static/app");
    }

    #[test]
    fn module_path_dirname_handles_file_at_root() {
        assert_eq!(module_path_dirname("entry.js"), "");
    }
}
