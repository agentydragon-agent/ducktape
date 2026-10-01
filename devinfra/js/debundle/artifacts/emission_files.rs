//! Checked ownership of prepared and emitted files with their matching indexes.

use anyhow::{Result, bail};

use super::{ArtifactIndexes, ChunkBundle, ChunkId, ImportRecord};

/// Paths and manifest inputs whose changes invalidate `ArtifactIndexes`.
#[derive(PartialEq, Eq)]
struct IndexedLayout {
    chunk_names: Vec<String>,
    chunks: Vec<IndexedChunkLayout>,
}

type IndexedChunkLayout = (
    ChunkId,
    String,
    String,
    String,
    Vec<ImportRecord>,
    Vec<(String, String)>,
);

impl ChunkBundle {
    fn indexed_layout(&self) -> IndexedLayout {
        IndexedLayout {
            chunk_names: (0..self.chunk_table.len())
                .map(|index| self.chunk_table.name(ChunkId(index)).to_string())
                .collect(),
            chunks: self
                .chunks
                .iter()
                .map(|chunk| {
                    let mut files = chunk
                        .js
                        .files
                        .iter()
                        .map(|file| (file.path.clone(), file.metadata.source_path.clone()))
                        .collect::<Vec<_>>();
                    files.sort();
                    (
                        chunk.chunk_id,
                        chunk.js.entry_file.clone(),
                        chunk.analysis.source_path.clone(),
                        chunk.analysis.entry_file.clone(),
                        chunk.analysis.imports.clone(),
                        files,
                    )
                })
                .collect(),
        }
    }
}

/// A [`ChunkBundle`] paired with the [`ArtifactIndexes`] built from exactly
/// that bundle.
///
/// The indexes are only reachable together with the artifact they were built
/// from. Mutations either go through [`IndexedArtifact::update`] (rebuilding
/// indexes) or [`IndexedArtifact::update_file_bodies`] (checking that their
/// indexed layout is unchanged). This makes it a type error
/// to hold indexes that are older than the artifact — the pipeline-level
/// stale-index bug class (consumers resolving imports against indexes built
/// before materialize created module files or vendor swaps removed chunks).
pub struct IndexedArtifact {
    artifact: ChunkBundle,
    indexes: ArtifactIndexes,
}

impl IndexedArtifact {
    pub fn new(artifact: ChunkBundle) -> Result<Self> {
        let indexes = ArtifactIndexes::build(&artifact)?;
        Ok(Self { artifact, indexes })
    }

    pub fn artifact(&self) -> &ChunkBundle {
        &self.artifact
    }

    /// Indexes matching the current artifact. Borrowing them keeps `self`
    /// borrowed, so they cannot outlive the next [`Self::update`].
    pub fn indexes(&self) -> &ArtifactIndexes {
        &self.indexes
    }

    pub fn into_artifact(self) -> ChunkBundle {
        self.artifact
    }

    /// Mutate AST bodies without changing the indexed file layout. The
    /// source/output path index remains valid; reject any accidental change
    /// to the file set, entry paths, or source paths before returning it.
    pub fn update_file_bodies<T>(
        mut self,
        mutate: impl FnOnce(&mut ChunkBundle, &ArtifactIndexes) -> Result<T>,
    ) -> Result<(Self, T)> {
        let layout = self.artifact.indexed_layout();
        let value = mutate(&mut self.artifact, &self.indexes)?;
        if self.artifact.indexed_layout() != layout {
            bail!("body-only emission pass changed the indexed chunk/file layout");
        }
        Ok((self, value))
    }

    /// Run an artifact mutation against the matching indexes, then rebuild
    /// the indexes from the mutated bundle.
    pub fn update<T>(
        self,
        mutate: impl FnOnce(ChunkBundle, &ArtifactIndexes) -> Result<(ChunkBundle, T)>,
    ) -> Result<(Self, T)> {
        let (artifact, value) = mutate(self.artifact, &self.indexes)?;
        Ok((Self::new(artifact)?, value))
    }
}

/// Emit-stage ownership: finalized lowered/pass-through files and the
/// indexes matching their final paths. Transformations may rewrite bodies
/// but cannot silently change the emission set's indexed file layout.
pub struct EmissionFiles {
    indexed: IndexedArtifact,
}

impl EmissionFiles {
    pub fn new(files: ChunkBundle) -> Result<Self> {
        Ok(Self {
            indexed: IndexedArtifact::new(files)?,
        })
    }

    pub fn from_prepared(indexed: IndexedArtifact) -> Self {
        Self { indexed }
    }

    pub fn files(&self) -> &ChunkBundle {
        self.indexed.artifact()
    }

    pub fn indexes(&self) -> &ArtifactIndexes {
        self.indexed.indexes()
    }

    pub fn rewrite_bodies<T>(
        self,
        rewrite: impl FnOnce(&mut ChunkBundle, &ArtifactIndexes) -> Result<T>,
    ) -> Result<(Self, T)> {
        let (indexed, value) = self.indexed.update_file_bodies(rewrite)?;
        Ok((Self { indexed }, value))
    }
}
