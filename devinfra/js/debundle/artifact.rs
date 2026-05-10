use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use relative_path::RelativePath;
use serde::Serialize;

use analysis::{ChunkId, ChunkTable};
use js_ast::{ParsedJsModule, emit_js_module};

pub const CANONICAL_CHUNK_ENTRY_FILE: &str = "entry.js";

#[derive(Default)]
pub struct LoadedJsChunks {
    pub chunk_order: Vec<ChunkId>,
    pub chunks: Vec<Option<JsChunk>>,
    pub chunk_table: ChunkTable,
}

pub struct JsPipelineArtifact {
    pub chunks: Vec<ChunkArtifact>,
    pub root_manifest: ArtifactManifest,
}

impl Default for JsPipelineArtifact {
    fn default() -> Self {
        Self {
            chunks: Vec::new(),
            root_manifest: ArtifactManifest::empty(),
        }
    }
}

pub struct ChunkArtifact {
    pub chunk_id: String,
    pub js: JsChunk,
    pub manifest: ChunkManifest,
}

pub struct JsChunk {
    pub entry_file: String,
    pub files: BTreeMap<String, JsFile>,
    pub metadata: ChunkMetadata,
}

pub struct JsFile {
    pub path: String,
    pub body: JsFileBody,
    pub header_lines: Vec<String>,
    pub metadata: FileMetadata,
}

pub struct JsFileAstParts {
    pub path: String,
    pub header_lines: Vec<String>,
    pub metadata: FileMetadata,
}

pub enum JsFileBody {
    Source(String),
    Ast(ParsedJsModule),
}

impl JsFile {
    pub fn source(&self) -> Option<&str> {
        match &self.body {
            JsFileBody::Source(source) => Some(source),
            JsFileBody::Ast(_) => None,
        }
    }

    pub fn into_source(self) -> Option<String> {
        match self.body {
            JsFileBody::Source(source) => Some(source),
            JsFileBody::Ast(_) => None,
        }
    }

    pub fn ast(&self) -> Option<&ParsedJsModule> {
        match &self.body {
            JsFileBody::Source(_) => None,
            JsFileBody::Ast(ast) => Some(ast),
        }
    }

    pub fn into_ast_parts(self) -> Option<(JsFileAstParts, ParsedJsModule)> {
        match self.body {
            JsFileBody::Ast(ast) => Some((
                JsFileAstParts {
                    path: self.path,
                    header_lines: self.header_lines,
                    metadata: self.metadata,
                },
                ast,
            )),
            JsFileBody::Source(_) => None,
        }
    }

    pub fn from_ast_parts(parts: JsFileAstParts, ast: ParsedJsModule) -> Self {
        Self {
            path: parts.path,
            body: JsFileBody::Ast(ast),
            header_lines: parts.header_lines,
            metadata: parts.metadata,
        }
    }

    pub fn is_ast(&self) -> bool {
        matches!(self.body, JsFileBody::Ast(_))
    }

    pub fn render_source(&self) -> Result<String> {
        match &self.body {
            JsFileBody::Source(source) => Ok(source.clone()),
            JsFileBody::Ast(ast) => emit_js_module(ast, &self.header_lines),
        }
    }
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
    pub output_path: Option<String>,
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
pub struct ParsedJsFileRecord {
    pub chunk_id: String,
    pub file: String,
    pub source_bytes: usize,
    pub parse_duration: Duration,
    pub analysis_duration: Duration,
}

#[derive(Debug, Clone, Serialize)]
pub struct ArtifactManifest {
    pub counts: ArtifactCounts,
    pub chunks: Vec<ArtifactChunkRecord>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub logical_modules: Option<RootLogicalModulesSummary>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub selected_module_lowerings: Option<Vec<SelectedModuleLowering>>,
    /// Path (manifest-relative) to the identifier rename priority queue
    /// side output, when this manifest was produced by a stage that
    /// emits to a writable directory (e.g. `write_js_tree`).
    /// `None` for early-pipeline manifests that never see a final
    /// output directory.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub identifier_rename_queue: Option<String>,
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

#[derive(Debug, Clone, Default, Serialize)]
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

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ImportSpecifierKind {
    Named,
    Default,
    Namespace,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum ImportReferenceKind {
    ArtifactPath,
    SourcePath,
}

#[derive(Debug, Clone)]
pub struct ResolvedImportReference {
    pub kind: ImportReferenceKind,
    pub target_chunk_id: String,
    pub target_file: String,
    pub target_path: String,
}

#[derive(Debug, Clone)]
pub struct ResolvedManifestImport {
    pub caller_chunk_id: String,
    pub caller_file: String,
    pub source: String,
    pub target: ResolvedImportReference,
    pub named_imports: Vec<String>,
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

impl LoadedJsChunks {
    pub fn list_chunk_ids(&self) -> Vec<String> {
        if self.chunk_order.is_empty() {
            self.chunks
                .iter()
                .enumerate()
                .filter_map(|(i, chunk)| {
                    chunk
                        .as_ref()
                        .map(|_| self.chunk_table.name(ChunkId(i)).to_string())
                })
                .collect()
        } else {
            self.chunk_order
                .iter()
                .map(|id| self.chunk_table.name(*id).to_string())
                .collect()
        }
    }

    pub fn take_chunk(&mut self, chunk_id: ChunkId) -> Option<JsChunk> {
        self.chunks.get_mut(chunk_id.0).and_then(|slot| slot.take())
    }
}

impl ArtifactManifest {
    pub fn empty() -> Self {
        Self {
            counts: ArtifactCounts {
                chunks: 0,
                kept_top_level_declaration_owners: 0,
                top_level_side_effects: 0,
                export_aliases: 0,
                unresolved_exports: 0,
                selected_module_lowerings: None,
            },
            chunks: Vec::new(),
            logical_modules: None,
            selected_module_lowerings: None,
            identifier_rename_queue: None,
            output_metrics: None,
        }
    }
}

impl JsPipelineArtifact {
    pub fn list_chunk_ids(&self) -> Vec<String> {
        self.chunks
            .iter()
            .map(|chunk| chunk.chunk_id.clone())
            .collect()
    }

    pub fn has_chunk(&self, chunk_id: &str) -> bool {
        self.find_chunk(chunk_id).is_some()
    }

    pub fn find_chunk(&self, chunk_id: &str) -> Option<&ChunkArtifact> {
        self.chunks.iter().find(|chunk| chunk.chunk_id == chunk_id)
    }

    pub fn chunk(&self, chunk_id: &str) -> Result<&ChunkArtifact> {
        self.find_chunk(chunk_id)
            .with_context(|| format!("missing artifact chunk {chunk_id}"))
    }

    pub fn find_chunk_mut(&mut self, chunk_id: &str) -> Option<&mut ChunkArtifact> {
        self.chunks
            .iter_mut()
            .find(|chunk| chunk.chunk_id == chunk_id)
    }

    pub fn chunk_mut(&mut self, chunk_id: &str) -> Result<&mut ChunkArtifact> {
        self.find_chunk_mut(chunk_id)
            .with_context(|| format!("missing artifact chunk {chunk_id}"))
    }

    pub fn find_js_chunk(&self, chunk_id: &str) -> Option<&JsChunk> {
        self.find_chunk(chunk_id).map(|chunk| &chunk.js)
    }

    pub fn js_chunk(&self, chunk_id: &str) -> Result<&JsChunk> {
        Ok(&self.chunk(chunk_id)?.js)
    }

    pub fn find_js_chunk_mut(&mut self, chunk_id: &str) -> Option<&mut JsChunk> {
        self.find_chunk_mut(chunk_id).map(|chunk| &mut chunk.js)
    }

    pub fn js_chunk_mut(&mut self, chunk_id: &str) -> Result<&mut JsChunk> {
        Ok(&mut self.chunk_mut(chunk_id)?.js)
    }

    pub fn remove_chunk(&mut self, chunk_id: &str) -> Option<ChunkArtifact> {
        let index = self
            .chunks
            .iter()
            .position(|chunk| chunk.chunk_id == chunk_id)?;
        Some(self.chunks.remove(index))
    }

    pub fn retain_chunks(&mut self, mut keep: impl FnMut(&str) -> bool) {
        self.chunks.retain(|chunk| keep(&chunk.chunk_id));
    }

    pub fn chunk_source_path(&self, chunk_id: &str) -> Option<String> {
        self.find_chunk(chunk_id)
            .map(|chunk| chunk.manifest.source_path.clone())
            .or_else(|| {
                self.find_js_chunk(chunk_id)
                    .and_then(|chunk| chunk.metadata.source_path.clone())
            })
            .or_else(|| Some(format!("{chunk_id}.js")))
    }

    pub fn source_import_resolver<'a>(
        &'a self,
        indexes: &'a ArtifactIndexes,
    ) -> ArtifactSourceImportResolver<'a> {
        ArtifactSourceImportResolver {
            artifact: self,
            indexes,
        }
    }
}

pub struct ArtifactSourceImportResolver<'a> {
    artifact: &'a JsPipelineArtifact,
    indexes: &'a ArtifactIndexes,
}

impl ArtifactSourceImportResolver<'_> {
    pub fn resolve(
        &self,
        source: &str,
        caller_chunk_id: &str,
        caller_file: &str,
    ) -> Result<Option<(String, String, String)>> {
        if source.is_empty() || (!source.starts_with('.') && !source.starts_with('/')) {
            return Ok(None);
        }
        let Some(caller_source_path) =
            source_path_for_artifact_file(self.artifact, caller_chunk_id, caller_file)?
        else {
            return Ok(None);
        };
        let Some(imported_source_path) =
            resolve_chunk_source_path_reference(source, &caller_source_path)
        else {
            return Ok(None);
        };
        let Some(target_chunk_id) = self.indexes.chunk_id_for_source(&imported_source_path) else {
            return Ok(None);
        };
        let Some(target_entry_file) = get_chunk_entry_path(self.artifact, &target_chunk_id) else {
            return Ok(None);
        };
        let path = artifact_file_output_path(self.artifact, &target_chunk_id, &target_entry_file)
            .unwrap_or_else(|| {
                join_module_path(&[target_chunk_id.as_str(), target_entry_file.as_str()])
            });
        Ok(Some((target_chunk_id, target_entry_file, path)))
    }
}

#[derive(Debug, Clone)]
pub struct ArtifactIndexes {
    chunk_id_index: BTreeMap<String, usize>,
    output_path_index: BTreeMap<String, (String, String)>,
    source_chunk_index: BTreeMap<String, String>,
    chunk_source_paths: BTreeMap<String, String>,
    file_source_paths: BTreeMap<(String, String), String>,
    entry_files: BTreeMap<String, String>,
    file_output_paths: BTreeMap<(String, String), String>,
    manifest_imports_by_target_chunk: BTreeMap<String, Vec<ResolvedManifestImport>>,
}

impl ArtifactIndexes {
    pub fn build(artifact: &JsPipelineArtifact) -> Result<Self> {
        let mut chunk_id_index = BTreeMap::new();
        let mut output_path_index = BTreeMap::new();
        let mut source_chunk_index = BTreeMap::new();
        let mut chunk_source_paths = BTreeMap::new();
        let mut file_source_paths = BTreeMap::new();
        let mut entry_files = BTreeMap::new();
        let mut file_output_paths = BTreeMap::new();

        for (index, chunk_artifact) in artifact.chunks.iter().enumerate() {
            let chunk_id = &chunk_artifact.chunk_id;
            if let Some(existing) = chunk_id_index.insert(chunk_id.clone(), index) {
                bail!("Duplicate chunk id {chunk_id}: indexes {existing} and {index}");
            }
            let chunk = &chunk_artifact.js;
            entry_files.insert(chunk_id.clone(), chunk.entry_file.clone());
            if let Some(source_path) = artifact.chunk_source_path(&chunk_id) {
                if let Some(existing) =
                    source_chunk_index.insert(source_path.clone(), chunk_id.clone())
                {
                    bail!("Duplicate chunk sourcePath {source_path}: {existing} and {chunk_id}");
                }
                chunk_source_paths.insert(chunk_id.clone(), source_path);
            }
            for file_path in list_chunk_file_paths(chunk) {
                let Some(file) = chunk.files.get(&file_path) else {
                    continue;
                };
                let key = (chunk_id.clone(), file_path.clone());
                if let Some(source_path) = file
                    .metadata
                    .source_path
                    .clone()
                    .or_else(|| chunk_source_paths.get(chunk_id).cloned())
                {
                    file_source_paths.insert(key.clone(), source_path);
                }
                if let Some(output_path) =
                    artifact_file_output_path_from_parts(&chunk_id, &file_path, file)
                {
                    if let Some(existing) =
                        output_path_index.insert(output_path.clone(), key.clone())
                    {
                        bail!(
                            "Duplicate artifact output path {output_path}: {}/{} and {}/{}",
                            existing.0,
                            existing.1,
                            key.0,
                            key.1
                        );
                    }
                    file_output_paths.insert(key, output_path);
                }
            }
        }

        let mut indexes = Self {
            chunk_id_index,
            output_path_index,
            source_chunk_index,
            chunk_source_paths,
            file_source_paths,
            entry_files,
            file_output_paths,
            manifest_imports_by_target_chunk: BTreeMap::new(),
        };
        indexes.index_manifest_imports(artifact);
        Ok(indexes)
    }

    pub fn chunk_index(&self, chunk_id: &str) -> Option<usize> {
        self.chunk_id_index.get(chunk_id).copied()
    }

    pub fn chunk_id_for_source(&self, source_path: &str) -> Option<String> {
        self.source_chunk_index.get(source_path).cloned()
    }

    fn resolve_artifact_output_reference(
        &self,
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
        self.output_path_index.get(&resolved_path).cloned()
    }

    pub fn resolve_runtime_import_reference(
        &self,
        source: &str,
        caller_chunk_id: &str,
        caller_file: &str,
    ) -> Option<ResolvedImportReference> {
        self.resolve_artifact_output_reference(source, caller_chunk_id, caller_file)
            .map(|(target_chunk_id, target_file)| {
                let target_path = self
                    .file_output_paths
                    .get(&(target_chunk_id.clone(), target_file.clone()))
                    .cloned()
                    .unwrap_or_else(|| join_module_path(&[&target_chunk_id, &target_file]));
                ResolvedImportReference {
                    kind: ImportReferenceKind::ArtifactPath,
                    target_chunk_id,
                    target_file,
                    target_path,
                }
            })
            .or_else(|| self.resolve_source_path_reference(source, caller_chunk_id, caller_file))
    }

    fn resolve_source_path_reference(
        &self,
        source: &str,
        caller_chunk_id: &str,
        caller_file: &str,
    ) -> Option<ResolvedImportReference> {
        if source.is_empty() || (!source.starts_with('.') && !source.starts_with('/')) {
            return None;
        }
        let caller_source_path = self
            .file_source_paths
            .get(&(caller_chunk_id.to_string(), caller_file.to_string()))
            .or_else(|| self.chunk_source_paths.get(caller_chunk_id))?;
        let imported_source_path = resolve_chunk_source_path_reference(source, caller_source_path)?;
        let target_chunk_id = self.source_chunk_index.get(&imported_source_path)?.clone();
        let target_entry_file = self.entry_files.get(&target_chunk_id)?.clone();
        let path = self
            .file_output_paths
            .get(&(target_chunk_id.clone(), target_entry_file.clone()))
            .cloned()
            .unwrap_or_else(|| join_module_path(&[&target_chunk_id, &target_entry_file]));
        Some(ResolvedImportReference {
            kind: ImportReferenceKind::SourcePath,
            target_chunk_id,
            target_file: target_entry_file,
            target_path: path,
        })
    }

    pub fn manifest_imports_targeting_chunk<'a>(
        &'a self,
        target_chunk_id: &str,
    ) -> impl Iterator<Item = &'a ResolvedManifestImport> {
        self.manifest_imports_by_target_chunk
            .get(target_chunk_id)
            .into_iter()
            .flat_map(|imports| imports.iter())
    }

    fn index_manifest_imports(&mut self, artifact: &JsPipelineArtifact) {
        for chunk in &artifact.chunks {
            let caller_chunk_id = chunk.chunk_id.clone();
            let caller_file = chunk.manifest.entry_file.clone();
            for import in &chunk.manifest.imports {
                let Some(target) = self.resolve_runtime_import_reference(
                    &import.source,
                    &caller_chunk_id,
                    &caller_file,
                ) else {
                    continue;
                };
                let record = ResolvedManifestImport {
                    caller_chunk_id: caller_chunk_id.clone(),
                    caller_file: caller_file.clone(),
                    source: import.source.clone(),
                    target,
                    named_imports: import
                        .specifiers
                        .iter()
                        .filter(|specifier| specifier.kind == ImportSpecifierKind::Named)
                        .map(|specifier| {
                            specifier
                                .imported
                                .clone()
                                .unwrap_or_else(|| specifier.local.clone())
                        })
                        .collect(),
                };
                self.manifest_imports_by_target_chunk
                    .entry(record.target.target_chunk_id.clone())
                    .or_default()
                    .push(record);
            }
        }
    }
}

pub fn load_js_chunks(
    input_root: &Path,
    js_list_path: &Path,
) -> Result<(LoadedJsChunks, LoadedJsChunksManifest)> {
    let js_files = parse_js_list(
        &fs::read_to_string(js_list_path)
            .with_context(|| format!("reading {}", js_list_path.display()))?,
    )?;
    let mut chunks = LoadedJsChunks::default();
    for source_path in &js_files {
        let absolute_path = input_root.join(source_path);
        let entry_file = Path::new(source_path)
            .file_name()
            .and_then(|value| value.to_str())
            .context("source path missing file name")?
            .to_string();
        let chunk_name = chunk_id_for_js_path(source_path)?;
        let chunk_id = chunks.chunk_table.intern(chunk_name.clone());
        let content = fs::read_to_string(&absolute_path)
            .with_context(|| format!("reading {}", absolute_path.display()))?;
        let mut files = BTreeMap::new();
        files.insert(
            entry_file.clone(),
            JsFile {
                path: entry_file.clone(),
                body: JsFileBody::Source(content),
                header_lines: Vec::new(),
                metadata: FileMetadata {
                    chunk_id: Some(chunk_name),
                    chunk_file: Some(entry_file.clone()),
                    role: Some(FileRole::Entry),
                    source_path: Some(source_path.clone()),
                    ..Default::default()
                },
            },
        );
        chunks.chunk_order.push(chunk_id);
        // Extend the vec to fit the new chunk id.
        while chunks.chunks.len() <= chunk_id.0 {
            chunks.chunks.push(None);
        }
        chunks.chunks[chunk_id.0] = Some(JsChunk {
            entry_file,
            files,
            metadata: ChunkMetadata {
                source_path: Some(source_path.clone()),
                module_extraction_state: None,
            },
        });
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
    Ok((chunks, manifest))
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
    let chunk_artifact = artifact.chunk(&chunk_id)?;
    let chunk = &chunk_artifact.js;
    let chunk_out_dir = out_dir.join(path_from_module_path(&chunk_id));
    fs::create_dir_all(&chunk_out_dir)?;
    let metrics = list_chunk_file_paths(chunk)
        .into_iter()
        .map(|file| {
            materialize_chunk_file(
                chunk,
                &chunk_id,
                out_dir,
                &chunk_out_dir,
                selected_module_by_chunk_file,
                file,
            )
        })
        .collect::<Result<Vec<_>>>()?;
    let mut manifest = chunk_artifact.manifest.clone();
    manifest.output_metrics = Some(OutputMetrics::from_file_metrics(
        metrics
            .iter()
            .map(|metric| chunk_relative_metric(&chunk_id, metric)),
    ));
    fs::write(
        chunk_out_dir.join("manifest.json"),
        serde_json::to_string_pretty(&manifest)? + "\n",
    )?;
    Ok(metrics)
}

fn materialize_chunk_file(
    chunk: &JsChunk,
    chunk_id: &str,
    out_dir: &Path,
    chunk_out_dir: &Path,
    selected_module_by_chunk_file: &BTreeMap<(String, String), &SelectedModuleLowering>,
    file: String,
) -> Result<OutputFileMetric> {
    let file_artifact = chunk
        .files
        .get(&file)
        .with_context(|| format!("missing artifact file {chunk_id}/{file}"))?;
    let rendered = file_artifact.render_source()?;
    let output_path = artifact_file_output_path_from_parts(chunk_id, &file, file_artifact)
        .unwrap_or_else(|| join_module_path(&[chunk_id, &file]));
    let target_path = if file_artifact.metadata.output_path.is_some() {
        out_dir.join(path_from_module_path(&output_path))
    } else {
        chunk_out_dir.join(path_from_module_path(&file))
    };
    if let Some(parent) = target_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let metric = output_file_metric(
        chunk_id,
        &output_path,
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
        .chunks
        .iter()
        .flat_map(|chunk| chunk.manifest.selected_module_lowerings.iter().flatten())
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
    output_path: &str,
    artifact_file_path: &str,
    rendered: &str,
    selected_module_by_chunk_file: &BTreeMap<(String, String), &SelectedModuleLowering>,
    role: Option<FileRole>,
) -> Result<OutputFileMetric> {
    let lowering = selected_module_by_chunk_file
        .get(&(chunk_id.to_string(), artifact_file_path.to_string()))
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
        file: output_path.to_string(),
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
    let chunk_artifact = artifact.find_chunk(chunk_id)?;
    let chunk = &chunk_artifact.js;
    if !chunk.entry_file.is_empty() && chunk.files.contains_key(&chunk.entry_file) {
        return Some(chunk.entry_file.clone());
    }
    Some(&chunk_artifact.manifest)
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

pub fn artifact_file_output_path(
    artifact: &JsPipelineArtifact,
    chunk_id: &str,
    file: &str,
) -> Option<String> {
    let chunk = artifact.find_js_chunk(chunk_id)?;
    let file_artifact = chunk.files.get(file)?;
    artifact_file_output_path_from_parts(chunk_id, file, file_artifact)
}

fn artifact_file_output_path_from_parts(
    chunk_id: &str,
    file: &str,
    file_artifact: &JsFile,
) -> Option<String> {
    file_artifact
        .metadata
        .output_path
        .clone()
        .or_else(|| Some(join_module_path(&[chunk_id, file])))
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
    let Some(chunk) = artifact.find_js_chunk(chunk_id) else {
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

pub fn resolve_chunk_source_path_reference(
    source: &str,
    caller_source_path: &str,
) -> Option<String> {
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
