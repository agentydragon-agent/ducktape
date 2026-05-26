//! CLI verb `debundle module merge`: splice source YAML modules into a
//! target YAML module and delete the sources.
//!
//! v1 scope is a pure YAML splice. There is no realizability or
//! factorization gate (see followup task #79 for `--validate`). The
//! splice operates on the generic `serde_yaml::Value` shape so the
//! operation never has to understand binding semantics, only the
//! `members:` and `anonymous_statements:` sequences that the spec
//! authoring format publishes.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow, bail};
use clap::{Args as ClapArgs, Subcommand};
use serde_yaml::{Mapping, Value};

/// Top-level `debundle module ...` argument shape.
#[derive(Debug, ClapArgs)]
pub struct ModuleArgs {
    #[command(subcommand)]
    command: ModuleCommand,
}

#[derive(Debug, Subcommand)]
enum ModuleCommand {
    /// Splice source YAMLs into a target YAML, deleting sources.
    Merge(MergeArgs),
}

#[derive(Debug, ClapArgs)]
pub struct MergeArgs {
    /// Root directory containing the per-module YAML tree.
    #[arg(long = "modules", env = "DEBUNDLE_MODULES")]
    pub modules_root: PathBuf,

    /// Target module path (relative to --modules) to merge into.
    #[arg(long = "target")]
    pub target: PathBuf,

    /// Source module paths (relative to --modules) to merge in.
    #[arg(required = true)]
    pub sources: Vec<PathBuf>,
}

/// Summary returned by [`merge_modules`].
#[derive(Debug, Clone)]
pub struct MergeSummary {
    /// Absolute path of the rewritten target.
    pub target: PathBuf,
    /// Absolute paths of source files that were merged in and deleted.
    pub merged_sources: Vec<PathBuf>,
}

impl MergeSummary {
    /// Render the one-line stdout summary.
    pub fn summary_line(&self) -> String {
        format!(
            "merged {} source(s) into {}",
            self.merged_sources.len(),
            self.target.display()
        )
    }
}

/// Run the `debundle module ...` command tree.
pub fn run_module_cli(args: ModuleArgs) -> Result<()> {
    match args.command {
        ModuleCommand::Merge(merge) => {
            eprintln!(
                "warning: `debundle module merge` is deprecated; use `debundle modules \
                 merge` instead."
            );
            run_merge(merge)
        }
    }
}

/// Public entry point for the merge verb. Used by the top-level
/// `debundle modules merge` and by the deprecated `debundle module
/// merge` alias.
pub fn run_merge(merge: MergeArgs) -> Result<()> {
    let sources: Vec<&Path> = merge.sources.iter().map(PathBuf::as_path).collect();
    let summary = merge_modules(&merge.modules_root, &merge.target, &sources)?;
    println!("{}", summary.summary_line());
    Ok(())
}

/// Merge `sources` into `target` under `modules_root`, then delete the
/// source files.
///
/// `target` and each entry in `sources` are interpreted relative to
/// `modules_root` unless already absolute.
///
/// Returns an error if any source declares a `members:` entry whose
/// `name:` collides with the target or another source.
pub fn merge_modules(
    modules_root: &Path,
    target: &Path,
    sources: &[&Path],
) -> Result<MergeSummary> {
    let target_abs = resolve_under(modules_root, target);
    let source_abs: Vec<PathBuf> = sources
        .iter()
        .map(|p| resolve_under(modules_root, p))
        .collect();

    let mut target_doc = read_yaml(&target_abs)?;
    let mut existing_names = collect_member_names(&target_doc, &target_abs)?;
    let mut merged_source_labels: Vec<String> = Vec::new();

    for src in &source_abs {
        let src_doc = read_yaml(src)?;
        let src_names = collect_member_names(&src_doc, src)?;
        for name in &src_names {
            if !existing_names.insert(name.clone()) {
                bail!(
                    "duplicate member name \"{}\" in {} and {}",
                    name,
                    target_abs.display(),
                    src.display()
                );
            }
        }
        splice_sequence(&mut target_doc, "members", &src_doc, src)?;
        splice_sequence(&mut target_doc, "anonymous_statements", &src_doc, src)?;
        merged_source_labels.push(display_relative(modules_root, src));
    }

    let mut body = String::new();
    if !merged_source_labels.is_empty() {
        body.push_str("# merged from: ");
        body.push_str(&merged_source_labels.join(", "));
        body.push('\n');
    }
    body.push_str(
        &serde_yaml::to_string(&target_doc)
            .with_context(|| format!("serializing merged {}", target_abs.display()))?,
    );
    fs::write(&target_abs, body)
        .with_context(|| format!("writing merged {}", target_abs.display()))?;

    for src in &source_abs {
        fs::remove_file(src)
            .with_context(|| format!("deleting merged source {}", src.display()))?;
    }

    Ok(MergeSummary {
        target: target_abs,
        merged_sources: source_abs,
    })
}

fn resolve_under(root: &Path, rel: &Path) -> PathBuf {
    if rel.is_absolute() {
        rel.to_path_buf()
    } else {
        root.join(rel)
    }
}

fn display_relative(root: &Path, abs: &Path) -> String {
    abs.strip_prefix(root)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| abs.to_string_lossy().into_owned())
}

fn read_yaml(path: &Path) -> Result<Value> {
    let text = fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?;
    let parsed: Value =
        serde_yaml::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
    // Treat an empty file as an empty mapping so we can splice into it.
    Ok(match parsed {
        Value::Null => Value::Mapping(Mapping::new()),
        other => other,
    })
}

fn collect_member_names(doc: &Value, path: &Path) -> Result<BTreeSet<String>> {
    let mut names = BTreeSet::new();
    let Some(members) = sequence_field(doc, "members") else {
        return Ok(names);
    };
    for (idx, member) in members.iter().enumerate() {
        let Some(name) = member_name(member) else {
            continue;
        };
        if !names.insert(name.clone()) {
            return Err(anyhow!(
                "duplicate member name \"{}\" within {} (entry {})",
                name,
                path.display(),
                idx
            ));
        }
    }
    Ok(names)
}

fn member_name(member: &Value) -> Option<String> {
    let mapping = member.as_mapping()?;
    let selector = mapping
        .get(Value::String("selector".into()))?
        .as_mapping()?;
    let binding = selector
        .get(Value::String("binding".into()))?
        .as_mapping()?;
    let name = binding.get(Value::String("name".into()))?.as_str()?;
    Some(name.to_string())
}

fn sequence_field<'a>(doc: &'a Value, key: &str) -> Option<&'a Vec<Value>> {
    doc.as_mapping()
        .and_then(|m| m.get(Value::String(key.into())))
        .and_then(Value::as_sequence)
}

fn splice_sequence(
    target: &mut Value,
    key: &str,
    source_doc: &Value,
    source_path: &Path,
) -> Result<()> {
    let Some(extra) = sequence_field(source_doc, key) else {
        return Ok(());
    };
    if extra.is_empty() {
        return Ok(());
    }
    let extra = extra.clone();
    let mapping = target.as_mapping_mut().ok_or_else(|| {
        anyhow!(
            "target YAML is not a mapping; cannot splice \"{}\" from {}",
            key,
            source_path.display()
        )
    })?;
    let entry = mapping
        .entry(Value::String(key.into()))
        .or_insert_with(|| Value::Sequence(Vec::new()));
    if entry.is_null() {
        *entry = Value::Sequence(Vec::new());
    }
    let seq = entry.as_sequence_mut().ok_or_else(|| {
        anyhow!(
            "target field \"{}\" is not a sequence; cannot splice from {}",
            key,
            source_path.display()
        )
    })?;
    seq.extend(extra);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(root: &Path, rel: &str, body: &str) {
        let path = root.join(rel);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    #[test]
    fn merge_appends_members_and_deletes_sources() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();
        write(
            root,
            "target.yaml",
            "members:\n  - selector: { binding: { name: a } }\n",
        );
        write(
            root,
            "src1.yaml",
            "members:\n  - selector: { binding: { name: b } }\n",
        );
        write(
            root,
            "src2.yaml",
            "members:\n  - selector: { binding: { name: c } }\n",
        );

        let summary = merge_modules(
            root,
            Path::new("target.yaml"),
            &[Path::new("src1.yaml"), Path::new("src2.yaml")],
        )
        .unwrap();

        assert_eq!(summary.merged_sources.len(), 2);
        assert!(summary.summary_line().contains("merged 2 source(s) into"));
        assert!(!root.join("src1.yaml").exists());
        assert!(!root.join("src2.yaml").exists());

        let merged = fs::read_to_string(root.join("target.yaml")).unwrap();
        assert!(merged.contains("# merged from: src1.yaml, src2.yaml"));
        let doc: Value = serde_yaml::from_str(&merged).unwrap();
        let names: Vec<String> = doc["members"]
            .as_sequence()
            .unwrap()
            .iter()
            .map(|m| member_name(m).unwrap())
            .collect();
        assert_eq!(names, vec!["a", "b", "c"]);
    }

    #[test]
    fn duplicate_name_across_files_is_rejected() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();
        write(
            root,
            "target.yaml",
            "members:\n  - selector: { binding: { name: dup } }\n",
        );
        write(
            root,
            "src.yaml",
            "members:\n  - selector: { binding: { name: dup } }\n",
        );
        let err =
            merge_modules(root, Path::new("target.yaml"), &[Path::new("src.yaml")]).unwrap_err();
        let msg = format!("{err}");
        assert!(msg.contains("duplicate member name \"dup\""), "msg={msg}");
        // Source must not be deleted on failure.
        assert!(root.join("src.yaml").exists());
    }

    #[test]
    fn anonymous_statements_are_spliced_too() {
        let dir = TempDir::new().unwrap();
        let root = dir.path();
        write(
            root,
            "target.yaml",
            "members: []\nanonymous_statements:\n  - { kind: A }\n",
        );
        write(
            root,
            "src.yaml",
            "members: []\nanonymous_statements:\n  - { kind: B }\n",
        );
        merge_modules(root, Path::new("target.yaml"), &[Path::new("src.yaml")]).unwrap();
        let merged = fs::read_to_string(root.join("target.yaml")).unwrap();
        let doc: Value = serde_yaml::from_str(&merged).unwrap();
        let kinds: Vec<String> = doc["anonymous_statements"]
            .as_sequence()
            .unwrap()
            .iter()
            .map(|s| s["kind"].as_str().unwrap().to_string())
            .collect();
        assert_eq!(kinds, vec!["A", "B"]);
    }
}
