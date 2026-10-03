//! Source-file selection shared by selector-authoring and validation commands.

use std::path::{Path, PathBuf};
use anyhow::{Context, Result, bail};

/// Source-less inventory is allowed, but a requested chunk must have a root.
/// A source root alone does not request source-aware analysis.
pub fn optional_chunk_source_file(
    source_file: Option<&Path>,
    source_root: Option<&Path>,
    chunk: Option<&Path>,
) -> Result<Option<PathBuf>> {
    match (source_file, source_root, chunk) {
        (Some(source_file), _, None) => Ok(Some(source_file.to_path_buf())),
        (None, Some(source_root), Some(chunk)) => Ok(Some(source_root.join(chunk))),
        (Some(_), _, Some(_)) => bail!("use either --source-file or --source-root with --chunk, not both"),
        (None, None, Some(_)) => bail!("--chunk requires --source-root or DEBUNDLE_SOURCE_ROOT"),
        (None, _, None) => Ok(None),
    }
}

pub fn resolve_chunk_source_file(
    source_file: Option<&Path>,
    source_root: Option<&Path>,
    chunk: Option<&Path>,
) -> Result<PathBuf> {
    optional_chunk_source_file(source_file, source_root, chunk)?
        .context("a source chunk is required: pass --source-file or --source-root + --chunk")
}
