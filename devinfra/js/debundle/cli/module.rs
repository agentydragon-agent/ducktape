//! CLI verb `debundle modules merge`: splice source YAML modules into a
//! target YAML module and delete the sources. The companion
//! `debundle modules delete --force` verb removes a non-empty module.
//!
//! Both verbs run a realizability gate against the **post-edit**
//! partition before touching the filesystem. The gate reconstructs
//! the chunk's `OwnerGraph` from `owner_graph.json` (via
//! `OwnerGraph::from_report`), builds the post-edit `Partition` by
//! mapping each surviving spec module's bindings to a fresh
//! `ModuleId`, and runs `validate_factorization`. An unrealizable
//! verdict prints the cycle summary via `render_cycle_summary` and
//! the command exits non-zero without writing any file. `--no-verify`
//! skips the gate; `--dry-run` runs the gate but doesn't write.
//!
//! The YAML splice itself operates on the generic `serde_yaml::Value`
//! shape so the operation never has to understand binding semantics,
//! only the `members:` and `anonymous_statements:` sequences that the
//! spec authoring format publishes.

use std::collections::{BTreeSet, HashMap};
use std::fs;
use std::path::{Path, PathBuf};

use analysis::{
    ModuleId, OwnerGraph, OwnerGraphReport, OwnerId, Partition, render_cycle_summary,
    validate_factorization,
};
use anyhow::{Context, Result, anyhow, bail};
use clap::{Args as ClapArgs, Subcommand};
use serde_yaml::{Mapping, Value};
use spec_modules::{collect_module_files, is_module_yaml, read_module_file};

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

    /// Validate but do not modify any file.
    #[arg(long)]
    pub dry_run: bool,

    /// Skip the realizability gate. Don't use casually — bypassing
    /// it can let an unrealizable spec ship.
    #[arg(long)]
    pub no_verify: bool,

    /// `owner_graph.json` for the chunk being merged. Required for
    /// the realizability gate; ignored when `--no-verify` is set.
    #[arg(long = "graph", env = "DEBUNDLE_GRAPH")]
    pub owner_graph_path: Option<PathBuf>,
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

/// Top-level `debundle modules delete` argument shape.
#[derive(Debug, ClapArgs)]
pub struct DeleteArgs {
    /// Root directory containing the per-module YAML tree.
    #[arg(long = "modules", env = "DEBUNDLE_MODULES")]
    pub modules_root: PathBuf,

    /// Module paths (relative to --modules) to delete. Must be
    /// non-empty.
    #[arg(required = true)]
    pub paths: Vec<PathBuf>,

    /// Validate but do not delete any file.
    #[arg(long)]
    pub dry_run: bool,

    /// Skip the realizability gate. Don't use casually — bypassing
    /// it on a non-empty deletion can let an unrealizable spec ship.
    #[arg(long)]
    pub no_verify: bool,

    /// Delete a module that still has members or anonymous statements.
    /// Default refuses non-empty deletions; pass `--force` to override.
    #[arg(long)]
    pub force: bool,

    /// `owner_graph.json` for the chunk being edited. Required for
    /// the realizability gate on non-empty `--force` deletions;
    /// ignored when `--no-verify` is set or when every target module
    /// is structurally empty (no-op gate).
    #[arg(long = "graph", env = "DEBUNDLE_GRAPH")]
    pub owner_graph_path: Option<PathBuf>,
}

/// Summary returned by [`delete_modules`].
#[derive(Debug, Clone)]
pub struct DeleteSummary {
    /// Absolute paths of the YAML files that were deleted (or, in
    /// `dry-run` mode, would have been deleted).
    pub deleted: Vec<PathBuf>,
    /// Whether the call was a dry-run (no files were actually
    /// touched). When `true`, `deleted` lists the would-be paths.
    pub dry_run: bool,
}

impl DeleteSummary {
    /// Render the one-line stdout summary.
    pub fn summary_line(&self) -> String {
        if self.dry_run {
            format!("dry-run: would delete {} file(s)", self.deleted.len())
        } else {
            format!("deleted {} file(s)", self.deleted.len())
        }
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
///
/// Validation contract (per docs/cli.md § "Modules"):
///
/// * Default: run the realizability gate against the post-merge
///   partition. Accept and splice if `Verdict::Realizable`; reject
///   and exit non-zero with the same `render_cycle_summary`
///   diagnostic the pipeline prints if `Verdict::Unrealizable`.
/// * `--dry-run`: run the gate but do not modify any file.
/// * `--no-verify`: skip the gate; apply the merge regardless.
pub fn run_merge(merge: MergeArgs) -> Result<()> {
    if merge.no_verify {
        eprintln!(
            "warning: --no-verify skips the realizability gate; the merge YAML splice will \
             not be re-checked for cross-module cycles."
        );
    } else {
        let owner_graph_path = merge.owner_graph_path.as_deref().ok_or_else(|| {
            anyhow!(
                "realizability gate requires --graph (path to owner_graph.json) or \
                 --no-verify"
            )
        })?;
        let target_abs = resolve_under(&merge.modules_root, &merge.target);
        let source_abs: Vec<PathBuf> = merge
            .sources
            .iter()
            .map(|p| resolve_under(&merge.modules_root, p))
            .collect();
        let post_spec = post_merge_spec(&merge.modules_root, &target_abs, &source_abs)?;
        gate_post_edit_partition(owner_graph_path, &post_spec)?;
    }

    let sources: Vec<&Path> = merge.sources.iter().map(PathBuf::as_path).collect();
    if merge.dry_run {
        // Dry-run shape preview: load each file to confirm shape
        // before reporting the action. The full validate+write
        // pass would be the same minus the final `fs::write` /
        // `fs::remove_file`.
        let summary = preview_merge(&merge.modules_root, &merge.target, &sources)?;
        println!(
            "dry-run: would merge {} source(s) into {}",
            summary.merged_sources.len(),
            summary.target.display()
        );
        return Ok(());
    }
    let summary = merge_modules(&merge.modules_root, &merge.target, &sources)?;
    println!("{}", summary.summary_line());
    Ok(())
}

/// Like `merge_modules` but without writing/deleting. Returns the
/// summary that would be produced. Used by `--dry-run`.
fn preview_merge(
    modules_root: &Path,
    target: &Path,
    sources: &[&Path],
) -> Result<MergeSummary> {
    let target_abs = if target.is_absolute() {
        target.to_path_buf()
    } else {
        modules_root.join(target)
    };
    let source_abs: Vec<PathBuf> = sources
        .iter()
        .map(|p| {
            if p.is_absolute() {
                p.to_path_buf()
            } else {
                modules_root.join(p)
            }
        })
        .collect();
    // Confirm every source + the target parse as YAML. This catches
    // syntactically broken files before any write would happen in a
    // non-dry-run.
    let _ = read_yaml(&target_abs)?;
    for src in &source_abs {
        let _ = read_yaml(src)?;
    }
    Ok(MergeSummary {
        target: target_abs,
        merged_sources: source_abs,
    })
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

/// Public entry point for `debundle modules delete`.
///
/// Validation contract (per docs/cli.md § "Modules"):
///
/// * Default: refuse the deletion of a module that still has members
///   or anonymous statements. For empty deletions, no gate run is
///   needed — the partition doesn't change.
/// * `--force`: override the non-empty check. For non-empty
///   deletions the realizability gate runs against the post-delete
///   partition (every binding previously owned by a deleted module
///   falls back to residual); an `Unrealizable` verdict rejects the
///   deletion.
/// * `--dry-run`: run the gate but do not delete any file.
/// * `--no-verify`: skip the gate; delete unconditionally.
///
/// All paths are resolved relative to `args.modules_root` unless
/// absolute. Paths that do not exist on disk are reported as an
/// error before any deletion is attempted; the operation is
/// best-effort atomic (collect-then-remove) but cannot roll back a
/// partial removal if the filesystem fails midway.
pub fn run_delete(args: DeleteArgs) -> Result<()> {
    if args.no_verify {
        eprintln!(
            "warning: --no-verify skips the realizability gate; the deletion will not be \
             re-checked for cross-module cycles."
        );
    }

    let paths_abs: Vec<PathBuf> = args
        .paths
        .iter()
        .map(|p| resolve_under(&args.modules_root, p))
        .collect();

    // Verify every path exists up-front so we never get stuck in a
    // partial-removal state on a typo.
    for p in &paths_abs {
        if !p.exists() {
            bail!("module path does not exist: {}", p.display());
        }
    }

    // Classify each module: empty (no members, no anonymous
    // statements) vs non-empty. Required for the `--force` check and
    // the empty-fast-path gate.
    let mut non_empty: Vec<(PathBuf, usize, bool)> = Vec::new();
    let mut all_empty = true;
    for p in &paths_abs {
        let doc = read_yaml(p)?;
        let member_count = sequence_field(&doc, "members").map_or(0, Vec::len);
        let has_anon = sequence_field(&doc, "anonymous_statements")
            .is_some_and(|s| !s.is_empty());
        if member_count > 0 || has_anon {
            all_empty = false;
            non_empty.push((p.clone(), member_count, has_anon));
        }
    }

    if !non_empty.is_empty() && !args.force {
        // Render a single-line refusal naming the first offender so
        // the user can see why; the additional non-empty paths fall
        // through `--force` once the user opts in.
        let (path, members, has_anon) = &non_empty[0];
        let anon_msg = if *has_anon {
            " (plus anonymous_statements)"
        } else {
            ""
        };
        bail!(
            "module {} has {} member(s){}; pass --force to delete anyway",
            path.display(),
            members,
            anon_msg,
        );
    }

    // Realizability gate. The all-empty fast path is a structural
    // no-op (an empty module owns no bindings and contributes no
    // anonymous statements, so removing it leaves the partition
    // unchanged). For non-empty `--force` deletions we run the full
    // gate against the post-delete partition.
    if !args.no_verify && !all_empty {
        let owner_graph_path = args.owner_graph_path.as_deref().ok_or_else(|| {
            anyhow!(
                "realizability gate requires --graph (path to owner_graph.json) for \
                 non-empty module deletion, or pass --no-verify"
            )
        })?;
        let post_spec = post_delete_spec(&args.modules_root, &paths_abs)?;
        gate_post_edit_partition(owner_graph_path, &post_spec)?;
    }

    let summary = delete_modules(&paths_abs, args.dry_run)?;
    println!("{}", summary.summary_line());
    Ok(())
}

/// Delete the given absolute paths (or, in `dry_run` mode, simply
/// return what would be deleted).
///
/// The caller is responsible for resolving relative paths and for
/// the empty/non-empty + gate decision; this function is the
/// filesystem half of `run_delete`.
pub fn delete_modules(paths: &[PathBuf], dry_run: bool) -> Result<DeleteSummary> {
    if dry_run {
        return Ok(DeleteSummary {
            deleted: paths.to_vec(),
            dry_run: true,
        });
    }
    let mut deleted: Vec<PathBuf> = Vec::new();
    for p in paths {
        fs::remove_file(p).with_context(|| format!("deleting {}", p.display()))?;
        deleted.push(p.clone());
    }
    Ok(DeleteSummary {
        deleted,
        dry_run: false,
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

// ---------------------------------------------------------------------
// Realizability gate hookup (task #84).
// ---------------------------------------------------------------------

/// Simulated post-edit spec state — one entry per surviving module,
/// each listing the binding names declared by its `members:` array.
/// `modules` is keyed by absolute YAML path so the gate's
/// module-id assignment is deterministic across runs.
#[derive(Debug, Clone)]
struct PostEditSpec {
    /// Surviving module YAML paths (absolute), each with the set of
    /// binding names it declares after the edit.
    modules: Vec<(PathBuf, BTreeSet<String>)>,
}

/// Build the post-merge spec view in memory without touching the
/// filesystem. Starts from the on-disk modules tree, drops the source
/// files, and folds their `members:` binding names into the target.
fn post_merge_spec(
    modules_root: &Path,
    target_abs: &Path,
    source_abs: &[PathBuf],
) -> Result<PostEditSpec> {
    let removed: BTreeSet<PathBuf> = source_abs.iter().cloned().collect();
    let mut modules: Vec<(PathBuf, BTreeSet<String>)> = Vec::new();
    for file in collect_module_files(modules_root)? {
        if removed.contains(&file) {
            continue;
        }
        let bindings = if file == target_abs {
            let mut combined = read_member_bindings(&file)?;
            for src in source_abs {
                combined.extend(read_member_bindings(src)?);
            }
            combined
        } else {
            read_member_bindings(&file)?
        };
        modules.push((file, bindings));
    }
    Ok(PostEditSpec { modules })
}

/// Build the post-delete spec view in memory. Drops the deleted YAML
/// paths from the modules tree; bindings they used to declare are
/// implicitly unclaimed in the resulting partition (i.e. fall back to
/// residual).
fn post_delete_spec(modules_root: &Path, deleted_abs: &[PathBuf]) -> Result<PostEditSpec> {
    let removed: BTreeSet<PathBuf> = deleted_abs.iter().cloned().collect();
    let mut modules: Vec<(PathBuf, BTreeSet<String>)> = Vec::new();
    for file in collect_module_files(modules_root)? {
        if removed.contains(&file) {
            continue;
        }
        modules.push((file.clone(), read_member_bindings(&file)?));
    }
    Ok(PostEditSpec { modules })
}

/// Parse a spec module YAML and return the set of `members[].selector.binding.name`
/// values it declares. Unparseable members are skipped (the gate
/// tolerates author noise so its rejection signal is "the partition
/// is unrealizable", not "your YAML is malformed").
fn read_member_bindings(path: &Path) -> Result<BTreeSet<String>> {
    if !is_module_yaml(path) {
        return Ok(BTreeSet::new());
    }
    let module = read_module_file(path)
        .with_context(|| format!("reading module {}", path.display()))?;
    let mut names: BTreeSet<String> = BTreeSet::new();
    for member in module.members {
        names.insert(member.selector.binding.name);
    }
    Ok(names)
}

/// Reconstruct the `OwnerGraph` from `owner_graph_path`, build the
/// `Partition` implied by `post_spec`, and run the realizability gate.
/// Returns `Ok(())` when the verdict is realizable. Prints the
/// `render_cycle_summary` blame report to stderr and returns an
/// `anyhow::Error` when unrealizable, so the CLI exit code is
/// non-zero and the caller bails before writing.
fn gate_post_edit_partition(owner_graph_path: &Path, post_spec: &PostEditSpec) -> Result<()> {
    let owner_graph_report: OwnerGraphReport = serde_json::from_str(
        &fs::read_to_string(owner_graph_path)
            .with_context(|| format!("reading {}", owner_graph_path.display()))?,
    )
    .with_context(|| {
        format!("parsing owner graph {}", owner_graph_path.display())
    })?;

    // The gate algorithm walks edges + partition, not declared sets.
    // Pass `&[]` for facts — `from_report` leaves `declared` empty,
    // which is fine for `check_realizability`/`validate_factorization`
    // (both consume the partition we build below, not the per-owner
    // declared field).
    let (owner_graph, _index) = OwnerGraph::from_report(&owner_graph_report, &[]);

    // owner_by_binding_name uses the Atom-only declared_bindings the
    // wire shape carries; that's enough because the spec author also
    // references bindings by name (no hygienic context). When a
    // declared binding name is ambiguous across owners the first one
    // wins — the materializer's spec validator catches that
    // separately as a duplicate-binding diagnostic.
    let mut owner_by_binding_name: HashMap<String, OwnerId> = HashMap::new();
    for (idx, node) in owner_graph_report.nodes.iter().enumerate() {
        let owner = OwnerId(idx);
        for b in &node.declared_bindings {
            owner_by_binding_name
                .entry(b.binding.to_string())
                .or_insert(owner);
        }
    }

    // ModuleId assignment: residual at logical:0, every surviving
    // spec module gets a fresh logical:N starting at 1. The label
    // map keeps the renderer's diagnostic readable — we use each
    // module's chunk-relative path as its `module_name` callback
    // output.
    let residual = ModuleId::logical(0);
    let mut of: Vec<ModuleId> = vec![residual; owner_graph.nodes.len()];
    let mut module_label_by_id: HashMap<ModuleId, String> =
        [(residual, "<residual>".to_string())].into_iter().collect();
    let mut next_idx = 1usize;
    for (path, bindings) in &post_spec.modules {
        let mid = ModuleId::logical(next_idx);
        next_idx += 1;
        module_label_by_id.insert(mid, path.to_string_lossy().into_owned());
        for name in bindings {
            if let Some(&owner) = owner_by_binding_name.get(name) {
                of[owner.0] = mid;
            }
        }
    }
    let partition = Partition::from_assignments(of, residual);

    let module_name = |m: ModuleId| {
        module_label_by_id
            .get(&m)
            .cloned()
            .unwrap_or_else(|| format!("logical:{}", m.0.0))
    };
    let report = validate_factorization(&owner_graph, &partition, &module_name);
    if report.cycles.is_empty() {
        return Ok(());
    }
    let summary = render_cycle_summary(&report.cycles);
    eprintln!("error: post-edit spec is unrealizable:\n{}", summary);
    bail!("realizability gate rejected the edit");
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
