use super::*;

/// Files produced by lowering, separate from their source bundle until the
/// pipeline assembles the bundle consumed by post-lowering passes.
pub struct LoweredChunkOutputs {
    source: ChunkBundle,
    target_dir: String,
    replacements: BTreeMap<ChunkId, MaterializedLogicalChunk>,
}

pub struct AssembledChunkOutputs {
    pub artifact: ChunkBundle,
    pub decomposition_by_chunk: HashMap<ChunkId, ChunkDecompositionOutput>,
}

impl LoweredChunkOutputs {
    /// Temporary adapter for post-lowering passes that still consume the
    /// bundle. Migrate those passes before removing this assembly step.
    pub fn into_bundle(mut self) -> AssembledChunkOutputs {
        let mut decomposition_by_chunk = HashMap::new();
        let chunks = self
            .source
            .chunks
            .into_iter()
            .map(|chunk| {
                if let Some(replacement) = self.replacements.remove(&chunk.chunk_id) {
                    let (output, decomposition) =
                        materialized_chunk_artifact(&self.target_dir, chunk.analysis, replacement);
                    decomposition_by_chunk.insert(chunk.chunk_id, decomposition);
                    output
                } else {
                    chunk
                }
            })
            .collect();
        AssembledChunkOutputs {
            artifact: ChunkBundle {
                chunks,
                chunk_table: self.source.chunk_table,
            },
            decomposition_by_chunk,
        }
    }
}

pub(crate) fn collect_materialized_logical_chunks(
    artifact: ChunkBundle,
    target_dir: &str,
    chunks: Vec<MaterializedLogicalChunk>,
) -> Result<LoweredChunkOutputs> {
    let mut replacements = BTreeMap::<ChunkId, MaterializedLogicalChunk>::new();
    for chunk in chunks {
        let chunk_id = chunk.chunk_id;
        if replacements.insert(chunk_id, chunk).is_some() {
            bail!(
                "materialize_logical_modules produced duplicate chunk_id: {}",
                artifact.chunk_table.name(chunk_id)
            );
        }
    }
    Ok(LoweredChunkOutputs {
        source: artifact,
        target_dir: target_dir.to_string(),
        replacements,
    })
}

pub(super) fn materialized_chunk_artifact(
    target_dir: &str,
    base_analysis: ChunkAnalysisReport,
    chunk: MaterializedLogicalChunk,
) -> (ChunkArtifact, ChunkDecompositionOutput) {
    let MaterializedLogicalChunk {
        chunk_id,
        target_file,
        source_path,
        files,
        file_records,
        applied,
        directory_dependency_facts,
        validation,
        report,
        // `unmatched_spec_claims` and `vendor_reference_rewrites` are
        // rolled up by `materialize_logical_modules` before this point;
        // downstream artifact construction doesn't carry them.
        unmatched_spec_claims: _,
        vendor_reference_rewrites: _,
    } = chunk;
    let manifest_files = file_records
        .iter()
        .map(|(file, role)| ChunkFileRecord {
            file: file.clone(),
            role: *role,
        })
        .collect();
    let logical_modules = ChunkLogicalModulesSummary {
        module_paths: report
            .final_module_contents
            .iter()
            .map(|module| module.path.clone())
            .collect(),
        target_dir: target_dir.to_string(),
    };
    let js = JsChunk {
        entry_file: target_file.clone(),
        files,
        metadata: ChunkMetadata { source_path },
    };
    let analysis = ChunkAnalysisReport {
        entry_file: target_file,
        files: manifest_files,
        ..base_analysis
    };

    let decomposition = ChunkDecompositionOutput {
        logical_modules,
        selected_module_lowerings: applied,
        directory_dependency_facts,
        validation,
    };
    (
        ChunkArtifact {
            chunk_id,
            js,
            analysis,
        },
        decomposition,
    )
}
