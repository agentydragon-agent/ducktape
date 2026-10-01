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
    let known_chunks: BTreeSet<ChunkId> =
        artifact.chunks.iter().map(|chunk| chunk.chunk_id).collect();
    let mut replacements = BTreeMap::<ChunkId, MaterializedLogicalChunk>::new();
    for chunk in chunks {
        if !known_chunks.contains(&chunk.chunk_id) {
            bail!(
                "materialize_logical_modules produced unknown chunk index: {}",
                chunk.chunk_id.0
            );
        }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn source_chunk(chunk_id: ChunkId, name: &str) -> ChunkArtifact {
        let entry_file = "entry.js".to_string();
        let source_path = format!("{name}.js");
        ChunkArtifact {
            chunk_id,
            js: JsChunk {
                entry_file: entry_file.clone(),
                files: Vec::new(),
                metadata: ChunkMetadata {
                    source_path: source_path.clone(),
                },
            },
            analysis: ChunkAnalysisReport {
                chunk_id: name.to_string(),
                source_path,
                entry_file,
                counts: Default::default(),
                files: Vec::new(),
                imports: Vec::new(),
                export_aliases: Vec::new(),
                unresolved_exports: Vec::new(),
                kept_top_level_declarations: Vec::new(),
            },
        }
    }

    #[test]
    fn unlowered_chunks_keep_their_source_order_and_metadata() {
        let mut chunk_table = ChunkTable::default();
        let first = chunk_table.intern("first".to_string());
        let second = chunk_table.intern("second".to_string());
        let source = ChunkBundle {
            chunks: vec![source_chunk(second, "second"), source_chunk(first, "first")],
            chunk_table,
        };
        let output = collect_materialized_logical_chunks(source, "", Vec::new())
            .unwrap()
            .into_bundle();
        assert!(output.decomposition_by_chunk.is_empty());
        assert_eq!(
            output
                .artifact
                .chunks
                .iter()
                .map(|chunk| (chunk.chunk_id, chunk.analysis.source_path.as_str()))
                .collect::<Vec<_>>(),
            [(second, "second.js"), (first, "first.js")]
        );
    }
}
