use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use clap::Parser;
use runfiles::{Runfiles, rlocation};
use serde::{Deserialize, Serialize};

use artifact::{JsPipelineArtifact, compute_js_asts, load_js_chunks};
use emit_harness::{EmitBrowserHarnessOptions, emit_browser_harness};
use logical_modules::{MaterializeLogicalModulesOptions, materialize_logical_modules};
use normalize::normalize_js_chunks;
use rewrite_specifiers::rewrite_chunk_entry_specifiers;
use spec::{MaterializeLogicalModulesConfig, SwapVendorChunksConfig, TransformSpec, VendorLevel};
use vendor::{
    SwapVendorOptions, apply_vendor_annotations, rename_vendor_exports, swap_vendor_chunks,
};
use write_tree::write_js_tree;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransformCli {
    pub spec_path: PathBuf,
    pub package_roots: HashMap<String, PathBuf>,
    pub packages_root: Option<PathBuf>,
}

/// Command-line arguments for the debundle transform pipeline.
///
/// Use [`TransformArgs::resolve`] to obtain a [`TransformCli`] with paths
/// resolved against Bazel runfiles when running as a `bazel run` target.
#[derive(Parser, Debug)]
#[command(
    name = "debundle",
    version,
    about = "Run the debundle transform pipeline described by --spec.",
    long_about = "Runs the transform pipeline described by the spec. Pipeline stages \
                  dispatch directly to registered functions; this target does not invoke \
                  Bazel from inside the pipeline. Specs are parsed as YAML."
)]
pub struct TransformArgs {
    /// Path to the transform spec YAML.
    #[arg(long)]
    pub spec: PathBuf,
    /// Map a package name to its source directory: `<pkg>=<dir>`. May be repeated.
    #[arg(long = "package-root", value_parser = parse_package_root_kv)]
    pub package_roots: Vec<(String, PathBuf)>,
    /// Root directory containing per-package sources (alternative to repeated --package-root).
    #[arg(long)]
    pub packages_root: Option<PathBuf>,
}

impl TransformArgs {
    /// Resolve all path arguments against Bazel runfiles (when present) and
    /// collapse `--package-root` pairs into a `HashMap`.
    pub fn resolve(self) -> TransformCli {
        let runfiles = Runfiles::create().ok();
        TransformCli {
            spec_path: resolve_runfiles_path(self.spec, runfiles.as_ref()),
            package_roots: self
                .package_roots
                .into_iter()
                .map(|(name, dir)| (name, resolve_runfiles_path(dir, runfiles.as_ref())))
                .collect(),
            packages_root: self
                .packages_root
                .map(|dir| resolve_runfiles_path(dir, runfiles.as_ref())),
        }
    }
}

fn parse_package_root_kv(value: &str) -> Result<(String, PathBuf), String> {
    let Some(separator) = value.find('=') else {
        return Err(format!(
            "--package-root must be in <package>=<dir> form, got {value}"
        ));
    };
    if separator == 0 || separator == value.len() - 1 {
        return Err(format!(
            "--package-root must be in <package>=<dir> form, got {value}"
        ));
    }
    Ok((
        value[..separator].to_string(),
        PathBuf::from(&value[separator + 1..]),
    ))
}

#[derive(Debug, Clone, Serialize)]
pub struct TransformRunSummary {
    #[serde(serialize_with = "serialize_duration_ms")]
    pub duration: Duration,
    pub spec_path: String,
    pub steps: Vec<TransformStepSummary>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TransformStepSummary {
    pub stage: PipelineStage,
    #[serde(serialize_with = "serialize_duration_ms")]
    pub duration: Duration,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PipelineStage {
    RewriteChunkEntrySpecifiers,
    ApplyVendorAnnotations,
    RenameVendorExports,
    SwapVendorChunks,
    MaterializeLogicalModules,
    WriteJsTree,
    EmitBrowserHarness,
}

impl PipelineStage {
    fn label(self) -> &'static str {
        match self {
            Self::RewriteChunkEntrySpecifiers => "rewrite_chunk_entry_specifiers",
            Self::ApplyVendorAnnotations => "apply_vendor_annotations",
            Self::RenameVendorExports => "rename_vendor_exports",
            Self::SwapVendorChunks => "swap_vendor_chunks",
            Self::MaterializeLogicalModules => "materialize_logical_modules",
            Self::WriteJsTree => "write_js_tree",
            Self::EmitBrowserHarness => "emit_browser_harness",
        }
    }
}

#[derive(Default)]
struct TransformState {
    artifact: JsPipelineArtifact,
}

/// Resolve a path through Bazel runfiles when present, otherwise pass through.
///
/// Lets the binary work as a standalone CLI (filesystem paths) and as a
/// Bazel-run target (runfiles-relative paths produced by `$(rlocationpath ...)`)
/// without a launcher wrapper. A path is treated as runfiles-relative only
/// when it actually resolves to a file inside the runfiles tree; otherwise
/// it's left for the caller's filesystem semantics.
fn resolve_runfiles_path(path: PathBuf, runfiles: Option<&Runfiles>) -> PathBuf {
    if path.is_absolute() {
        return path;
    }
    let Some(runfiles) = runfiles else {
        return path;
    };
    let Some(s) = path.to_str() else {
        return path;
    };
    rlocation!(runfiles, s)
        .filter(|resolved| resolved.exists())
        .unwrap_or(path)
}

pub fn render_transform_summary(summary: &TransformRunSummary) -> String {
    let mut out = format!(
        "Ran {} transform steps from {} in {}\n",
        summary.steps.len(),
        summary.spec_path,
        humantime::format_duration(summary.duration)
    );
    for step in &summary.steps {
        out.push_str(&format!(
            "- {} ({})\n",
            step.stage.label(),
            humantime::format_duration(step.duration),
        ));
    }
    out
}

pub fn run_transform_cli(cli: &TransformCli) -> Result<TransformRunSummary> {
    let spec = load_transform_spec(&cli.spec_path)?;
    validate_transform_spec(&spec)?;
    let started = Instant::now();
    let mut state = TransformState::default();
    let (artifact, _load_manifest) =
        load_js_chunks(&spec.inputs.input_root, &spec.inputs.js_list_path)?;
    state.artifact = artifact;
    compute_js_asts(&mut state.artifact, true)?;
    let (artifact, _normalize_manifest) = normalize_js_chunks(std::mem::take(&mut state.artifact))?;
    state.artifact = artifact;
    let mut steps = Vec::new();

    run_step(
        &mut steps,
        PipelineStage::RewriteChunkEntrySpecifiers,
        || rewrite_chunk_entry_specifiers(&mut state.artifact).map(|_| ()),
    )?;

    // Vendor stages: each is internally filtered by `level`, so it's
    // safe to always invoke them when `vendor` carries any entries.
    // `apply` runs unconditionally; `rename` and `swap` short-circuit
    // to no-ops when no entry has the right level.
    if !spec.vendor.is_empty() {
        run_step(&mut steps, PipelineStage::ApplyVendorAnnotations, || {
            apply_vendor_annotations(&state.artifact, &spec.vendor).map(|_| ())
        })?;
        if spec
            .vendor
            .values()
            .any(|m| matches!(m.level, VendorLevel::BoundaryRename | VendorLevel::Swap(_)))
        {
            run_step(&mut steps, PipelineStage::RenameVendorExports, || {
                rename_vendor_exports(&mut state.artifact, &spec.vendor).map(|_| ())
            })?;
        }
        if spec
            .vendor
            .values()
            .any(|m| matches!(m.level, VendorLevel::Swap(_)))
        {
            let SwapVendorChunksConfig {
                output_manifest_path,
                output_wrapper_dir,
                write,
            } = spec.swap_vendor_chunks.clone();
            run_step(&mut steps, PipelineStage::SwapVendorChunks, || {
                swap_vendor_chunks(
                    &mut state.artifact,
                    &spec.vendor,
                    SwapVendorOptions {
                        package_roots: &cli.package_roots,
                        packages_root: &cli.packages_root,
                        output_manifest_path,
                        output_wrapper_dir,
                        write,
                    },
                )
                .map(|_| ())
            })?;
        }
    }

    let materialise_chunk_ids: Vec<String> = spec
        .logical_modules
        .keys()
        .chain(spec.residual_modules.keys())
        .chain(spec.chunk_renames.keys())
        .cloned()
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect();
    if !materialise_chunk_ids.is_empty() {
        let MaterializeLogicalModulesConfig {
            file,
            prune_other_chunks,
            force,
            report_out_dir,
            report_summary_path,
            target_dir,
        } = spec.materialize_logical_modules.clone();
        run_step(&mut steps, PipelineStage::MaterializeLogicalModules, || {
            materialize_logical_modules(
                &mut state.artifact,
                &spec.logical_modules,
                &spec.residual_modules,
                &spec.chunk_renames,
                MaterializeLogicalModulesOptions {
                    chunk_ids: materialise_chunk_ids,
                    file,
                    prune_other_chunks,
                    force,
                    report_out_dir,
                    report_summary_path,
                    target_dir,
                },
            )
            .map(|_| ())
        })?;
    }

    if let Some(cfg) = &spec.write_js_tree {
        let out_dir = cfg.out_dir.clone();
        let force = cfg.force;
        run_step(&mut steps, PipelineStage::WriteJsTree, || {
            write_js_tree(&state.artifact, &out_dir, force).map(|_| ())
        })?;
    }

    if let Some(cfg) = &spec.emit_browser_harness {
        let opts = EmitBrowserHarnessOptions {
            asset_summary_path: cfg.asset_summary_path.clone(),
            force: cfg.force,
            out_dir: cfg.out_dir.clone(),
            snapshot_root: cfg.snapshot_root.clone(),
        };
        run_step(&mut steps, PipelineStage::EmitBrowserHarness, || {
            emit_browser_harness(&state.artifact, &opts)?;
            Ok(())
        })?;
    }

    Ok(TransformRunSummary {
        duration: started.elapsed(),
        spec_path: cli.spec_path.display().to_string(),
        steps,
    })
}

fn run_step(
    steps: &mut Vec<TransformStepSummary>,
    stage: PipelineStage,
    body: impl FnOnce() -> Result<()>,
) -> Result<()> {
    let started = Instant::now();
    body()?;
    steps.push(TransformStepSummary {
        stage,
        duration: started.elapsed(),
    });
    Ok(())
}

fn load_transform_spec(spec_path: &Path) -> Result<TransformSpec> {
    let raw = fs::read(spec_path).with_context(|| format!("reading {}", spec_path.display()))?;
    serde_yaml::from_slice(&raw)
        .with_context(|| format!("Failed to parse {} as YAML", spec_path.display()))
}

fn validate_transform_spec(spec: &TransformSpec) -> Result<()> {
    if spec.inputs.input_root.as_os_str().is_empty() {
        bail!("Transform spec inputs.input_root must not be empty");
    }
    if spec.inputs.js_list_path.as_os_str().is_empty() {
        bail!("Transform spec inputs.js_list_path must not be empty");
    }
    Ok(())
}

fn serialize_duration_ms<S>(duration: &Duration, serializer: S) -> Result<S::Ok, S::Error>
where
    S: serde::Serializer,
{
    serializer.serialize_f64(duration.as_secs_f64() * 1000.0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use artifact::parse_js_list;

    #[derive(Serialize)]
    struct AssetSummaryFixture<'a> {
        #[serde(rename = "entryPoints")]
        entry_points: AssetSummaryEntryPoints<'a>,
    }

    #[derive(Serialize)]
    struct AssetSummaryEntryPoints<'a> {
        html: &'a str,
    }

    #[derive(Serialize)]
    struct PipelineSpecFixture<'a> {
        inputs: PipelineSpecInputs<'a>,
        emit_browser_harness: EmitBrowserHarnessFixture<'a>,
    }

    #[derive(Serialize)]
    struct PipelineSpecInputs<'a> {
        input_root: &'a Path,
        js_list_path: &'a Path,
    }

    #[derive(Serialize)]
    struct EmitBrowserHarnessFixture<'a> {
        asset_summary_path: &'a Path,
        force: bool,
        out_dir: &'a Path,
        snapshot_root: &'a Path,
    }

    #[test]
    fn parse_js_list_rejects_duplicates() {
        let err = parse_js_list("a.js\na.js\n").expect_err("expected duplicate rejection");
        assert!(err.to_string().contains("duplicate"));
    }

    #[test]
    fn parse_js_list_ignores_comments_and_blank_lines() {
        let parsed = parse_js_list("\n# comment\nfoo.js\nbar.js\n").expect("parse list");
        assert_eq!(parsed, vec!["foo.js", "bar.js"]);
    }

    #[test]
    fn parse_transform_cli_args_matches_js_surface() {
        let args = TransformArgs::try_parse_from([
            "debundle",
            "--spec",
            "spec.yaml",
            "--package-root",
            "pkg=/tmp/pkg",
            "--packages-root",
            "/tmp/packages",
        ])
        .expect("parse cli");
        let cli = args.resolve();
        assert_eq!(cli.spec_path, PathBuf::from("spec.yaml"));
        assert_eq!(
            cli.package_roots.get("pkg"),
            Some(&PathBuf::from("/tmp/pkg"))
        );
        assert_eq!(cli.packages_root, Some(PathBuf::from("/tmp/packages")));
    }

    #[test]
    fn run_transform_cli_writes_spec_pipeline_outputs() -> Result<()> {
        let temp = tempfile::tempdir()?;
        let root = temp.path();
        let snapshot = root.join("snapshot");
        let extracted = root.join("extracted");
        let out = root.join("out");
        fs::create_dir_all(snapshot.join("static"))?;
        fs::create_dir_all(&extracted)?;
        fs::write(
            snapshot.join("index.html"),
            r#"<!doctype html>
<html>
  <head>
    <link rel="modulepreload" href="./static/chunk-DuckMock.js">
  </head>
  <body>
    <script type="module" src="./static/index-DuckMock.js"></script>
  </body>
</html>
"#,
        )?;
        fs::write(
            snapshot.join("static/index-DuckMock.js"),
            "import { y } from './chunk-DuckMock.js';\nglobalThis.__value = y;\n",
        )?;
        fs::write(
            snapshot.join("static/chunk-DuckMock.js"),
            "export const y = 2;\n",
        )?;
        fs::write(
            extracted.join("js-files.txt"),
            "static/index-DuckMock.js\nstatic/chunk-DuckMock.js\n",
        )?;
        let js_list_path = extracted.join("js-files.txt");
        let asset_summary_path = extracted.join("asset-summary.json");
        fs::write(
            &asset_summary_path,
            serde_json::to_string(&AssetSummaryFixture {
                entry_points: AssetSummaryEntryPoints { html: "index.html" },
            })?,
        )?;
        let spec_path = root.join("transform-spec.yaml");
        fs::write(
            &spec_path,
            serde_yaml::to_string(&PipelineSpecFixture {
                inputs: PipelineSpecInputs {
                    input_root: &snapshot,
                    js_list_path: &js_list_path,
                },
                emit_browser_harness: EmitBrowserHarnessFixture {
                    asset_summary_path: &asset_summary_path,
                    force: true,
                    out_dir: &out,
                    snapshot_root: &snapshot,
                },
            })?,
        )?;

        let summary = run_transform_cli(&TransformCli {
            spec_path,
            package_roots: HashMap::new(),
            packages_root: None,
        })?;

        assert_eq!(summary.steps.len(), 2);
        assert!(out.join("bootstrap.js").exists());
        assert!(out.join("manifest.json").exists());
        let entry = fs::read_to_string(out.join("static/index-DuckMock/entry.js"))?;
        assert!(entry.contains("../chunk-DuckMock/entry.js"));

        // The harness tree must be self-contained: every path the manifest
        // records resolves to a file inside `out_dir`, with no leakage to
        // the original `extracted/` or `snapshots/` input trees. Consumers
        // (live proxy, downstream tools) may receive the manifest through
        // runfiles where the original input trees aren't co-located.
        let manifest: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(out.join("manifest.json"))?)?;
        assert!(
            manifest.get("schema_version").is_none(),
            "harness manifest should not carry a compatibility schema_version"
        );
        for field in [
            "source_html",
            "asset_summary_path",
            "chunks_manifest_path",
            "runtime_root",
            "out_dir",
        ] {
            let value = manifest
                .get(field)
                .and_then(serde_json::Value::as_str)
                .unwrap_or_else(|| panic!("manifest is missing {field}"));
            assert!(
                !value.starts_with('/') && !value.starts_with(".."),
                "manifest.{field} = {value:?} escapes the harness tree"
            );
            let resolved = out.join(value);
            assert!(
                resolved.exists(),
                "manifest.{field} = {value:?} resolves to {resolved:?} which does not exist"
            );
        }
        let chunks_manifest: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(out.join("chunks.manifest.json"))?)?;
        assert!(
            chunks_manifest.get("schema_version").is_none(),
            "chunks manifest should not carry a compatibility schema_version"
        );
        assert_eq!(
            chunks_manifest
                .get("chunks")
                .and_then(serde_json::Value::as_array)
                .map(Vec::len),
            Some(2)
        );
        Ok(())
    }
}
