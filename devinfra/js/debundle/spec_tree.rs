use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, bail};
use serde::Deserialize;

use spec::{
    ChunkRenames, EmitBrowserHarnessConfig, LoadJsChunksArgs, LogicalModule,
    MaterializeLogicalModulesConfig, Member, SwapMark, SwapVendorChunksConfig, TransformSpec,
    VendorLevel, VendorMark, VendorRole, WrapperShape,
};

#[derive(Debug, Clone)]
pub struct CompileSpecTreeOptions {
    pub config_path: PathBuf,
    pub modules_root: PathBuf,
    pub vendor_marks_path: PathBuf,
    pub ancillary_modules_path: Option<PathBuf>,
    pub out_root: Option<PathBuf>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthoringConfig {
    #[serde(default)]
    ui_version: Option<String>,
    default_out_root: PathBuf,
    main_chunk_id: String,
    source_roots: SourceRoots,
    logical_modules: LogicalModulesPolicy,
    browser_harness: BrowserHarnessPolicy,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceRoots {
    asset_summary_path: PathBuf,
    js_list_path: PathBuf,
    snapshot_root: PathBuf,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct LogicalModulesPolicy {
    chunk_ids: BTreeSet<String>,
    force: bool,
    #[serde(default)]
    target_dir: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserHarnessPolicy {
    force: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct VendorMarksFile {
    #[serde(default)]
    vendor_marks: Vec<VendorMarkSource>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct VendorMarkSource {
    chunk_path: String,
    identity: String,
    #[serde(default)]
    role: VendorRole,
    level: VendorLevelSource,
    #[serde(default)]
    package: Option<String>,
    #[serde(default)]
    version: Option<String>,
    #[serde(default)]
    subpath: Option<String>,
    #[serde(default)]
    wrapper_shape: Option<WrapperShape>,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum VendorLevelSource {
    Suppress,
    BoundaryRename,
    Swap,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct AncillaryModulesFile {
    #[serde(default)]
    modules: Vec<ModuleSource>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ModuleFile {
    path: String,
    #[serde(default)]
    members: Vec<Member>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct ModuleSource {
    chunk_id: String,
    path: String,
    #[serde(default)]
    members: Vec<Member>,
}

pub fn compile_spec_tree(options: &CompileSpecTreeOptions) -> Result<TransformSpec> {
    let config: AuthoringConfig = read_yaml(&options.config_path)?;
    let _ui_version = &config.ui_version;
    let out_root = options
        .out_root
        .clone()
        .unwrap_or_else(|| config.default_out_root.clone());
    let layout = OutputLayout::new(out_root);
    let (active_modules, deferred_members) =
        load_main_chunk_modules(&options.modules_root, &config.main_chunk_id)?;
    let mut module_sources = active_modules;
    if let Some(path) = &options.ancillary_modules_path {
        let ancillary: AncillaryModulesFile = read_yaml(path)?;
        module_sources.extend(ancillary.modules);
    }

    Ok(TransformSpec {
        inputs: LoadJsChunksArgs {
            input_root: config.source_roots.snapshot_root.clone(),
            js_list_path: config.source_roots.js_list_path.clone(),
        },
        vendor: vendor_map(read_yaml::<VendorMarksFile>(&options.vendor_marks_path)?.vendor_marks)?,
        logical_modules: logical_modules_map(module_sources, &config.logical_modules.chunk_ids),
        residual_modules: BTreeMap::new(),
        chunk_renames: chunk_renames_map(&config.main_chunk_id, deferred_members),
        swap_vendor_chunks: SwapVendorChunksConfig {
            output_manifest_path: Some(layout.vendor_manifest_path.clone()),
            output_wrapper_dir: Some(layout.vendor_wrapper_root.clone()),
            write: true,
        },
        materialize_logical_modules: MaterializeLogicalModulesConfig {
            file: None,
            prune_other_chunks: false,
            force: config.logical_modules.force,
            report_out_dir: Some(layout.reports_root.clone()),
            report_summary_path: Some(layout.reports_root.join("summary.json")),
            target_dir: config
                .logical_modules
                .target_dir
                .clone()
                .unwrap_or_default(),
        },
        write_js_tree: None,
        emit_browser_harness: Some(EmitBrowserHarnessConfig {
            asset_summary_path: config.source_roots.asset_summary_path,
            out_dir: layout.app_root,
            snapshot_root: config.source_roots.snapshot_root,
            force: config.browser_harness.force,
        }),
    })
}

pub fn write_compiled_spec(spec: &TransformSpec, out_path: &Path) -> Result<()> {
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("creating {}", parent.display()))?;
    }
    let body = serde_yaml::to_string(spec).context("serializing transform spec")?;
    fs::write(
        out_path,
        format!("# Generated transform spec. Edit the versioned YAML sources instead.\n{body}"),
    )
    .with_context(|| format!("writing {}", out_path.display()))
}

fn read_yaml<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T> {
    serde_yaml::from_str(
        &fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?,
    )
    .with_context(|| format!("parsing {}", path.display()))
}

#[derive(Debug, Clone)]
struct OutputLayout {
    app_root: PathBuf,
    reports_root: PathBuf,
    vendor_manifest_path: PathBuf,
    vendor_wrapper_root: PathBuf,
}

impl OutputLayout {
    fn new(app_root: PathBuf) -> Self {
        Self {
            reports_root: app_root.join("analysis/logical_modules"),
            vendor_manifest_path: app_root.join("vendors/manifest.json"),
            vendor_wrapper_root: app_root.join("vendors/generated"),
            app_root,
        }
    }
}

fn load_main_chunk_modules(
    modules_root: &Path,
    main_chunk_id: &str,
) -> Result<(Vec<ModuleSource>, Vec<Member>)> {
    let mut active = Vec::new();
    let mut deferred_members = Vec::new();
    let mut files = Vec::new();
    collect_module_files(modules_root, &mut files)?;
    for path in files {
        let is_deferred = is_deferred_yaml(&path);
        let suffix = if is_deferred {
            ".yaml.deferred"
        } else {
            ".yaml"
        };
        let expected_path = module_path_from_file(&path, modules_root, suffix);
        let data: ModuleFile = read_yaml(&path)?;
        if data.path != expected_path {
            bail!(
                "module file {} declares path {:?} but expected {:?}",
                path.display(),
                data.path,
                expected_path
            );
        }
        if is_deferred {
            deferred_members.extend(data.members);
        } else {
            active.push(ModuleSource {
                chunk_id: main_chunk_id.to_string(),
                path: data.path,
                members: data.members,
            });
        }
    }
    active.sort_by(|left, right| left.path.cmp(&right.path));
    Ok((active, deferred_members))
}

fn collect_module_files(root: &Path, out: &mut Vec<PathBuf>) -> Result<()> {
    for entry in fs::read_dir(root).with_context(|| format!("reading {}", root.display()))? {
        let path = entry
            .with_context(|| format!("walking {}", root.display()))?
            .path();
        if path.is_dir() {
            collect_module_files(&path, out)?;
        } else if is_module_yaml(&path) {
            out.push(path);
        }
    }
    out.sort();
    Ok(())
}

fn vendor_map(sources: Vec<VendorMarkSource>) -> Result<BTreeMap<String, VendorMark>> {
    let mut out = BTreeMap::new();
    for source in sources {
        let chunk_path = source.chunk_path.clone();
        let identity = source.identity.clone();
        let role = source.role;
        let level = source.into_vendor_level()?;
        out.insert(
            chunk_path,
            VendorMark {
                identity,
                role,
                level,
            },
        );
    }
    Ok(out)
}

impl VendorMarkSource {
    fn into_vendor_level(self) -> Result<VendorLevel> {
        match self.level {
            VendorLevelSource::Suppress => {
                self.ensure_no_swap_payload()?;
                Ok(VendorLevel::Suppress)
            }
            VendorLevelSource::BoundaryRename => {
                self.ensure_no_swap_payload()?;
                Ok(VendorLevel::BoundaryRename)
            }
            VendorLevelSource::Swap => Ok(VendorLevel::Swap(SwapMark {
                package: self
                    .package
                    .with_context(|| format!("vendor mark {} missing package", self.chunk_path))?,
                version: self
                    .version
                    .with_context(|| format!("vendor mark {} missing version", self.chunk_path))?,
                subpath: self
                    .subpath
                    .with_context(|| format!("vendor mark {} missing subpath", self.chunk_path))?,
                wrapper_shape: self.wrapper_shape,
            })),
        }
    }

    fn ensure_no_swap_payload(&self) -> Result<()> {
        if self.package.is_some()
            || self.version.is_some()
            || self.subpath.is_some()
            || self.wrapper_shape.is_some()
        {
            bail!(
                "vendor mark {} has swap-only fields but level is not swap",
                self.chunk_path
            );
        }
        Ok(())
    }
}

fn logical_modules_map(
    sources: Vec<ModuleSource>,
    allowed_chunk_ids: &BTreeSet<String>,
) -> BTreeMap<String, BTreeMap<String, LogicalModule>> {
    let mut out = BTreeMap::new();
    for source in sources {
        if !allowed_chunk_ids.contains(&source.chunk_id) {
            continue;
        }
        out.entry(source.chunk_id)
            .or_insert_with(BTreeMap::new)
            .insert(
                source.path,
                LogicalModule {
                    members: source.members,
                },
            );
    }
    out
}

fn chunk_renames_map(
    main_chunk_id: &str,
    deferred_members: Vec<Member>,
) -> BTreeMap<String, ChunkRenames> {
    if deferred_members.is_empty() {
        return BTreeMap::new();
    }
    BTreeMap::from([(
        main_chunk_id.to_string(),
        ChunkRenames {
            id: None,
            members: deferred_members,
        },
    )])
}

fn is_module_yaml(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.ends_with(".yaml") || name.ends_with(".yaml.deferred"))
}

fn is_deferred_yaml(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .is_some_and(|name| name.ends_with(".yaml.deferred"))
}

fn module_path_from_file(path: &Path, root: &Path, suffix: &str) -> String {
    let relative = path
        .strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/");
    relative
        .strip_suffix(suffix)
        .unwrap_or(&relative)
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_yaml::Value;

    fn write_file(path: &Path, body: &str) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    fn fixture(root: &Path) -> CompileSpecTreeOptions {
        let config = root.join("spec_config.yaml");
        let modules = root.join("modules");
        let vendor_marks = root.join("sources/vendor/vendor_marks.yaml");
        let ancillary = root.join("sources/logical/ancillary_chunk_modules.yaml");
        write_file(
            &config,
            r#"ui_version: test
default_out_root: out/default
main_chunk_id: static/main
source_roots:
  asset_summary_path: extracted/asset-summary.json
  js_list_path: extracted/js-files.txt
  snapshot_root: snapshots/test
logical_modules:
  chunk_ids:
    - static/main
    - static/extra
  force: true
  target_dir:
browser_harness:
  force: true
"#,
        );
        write_file(
            &vendor_marks,
            r#"vendor_marks:
  - level: swap
    chunk_path: static/vendor.js
    identity: example
    role: worker
    package: pkg
    version: 1.2.3
    subpath: dist/index.js
    wrapper_shape: named_from_module_default
"#,
        );
        write_file(
            &modules.join("active.yaml"),
            r#"path: active
members:
  - name: No
    selector:
      binding:
        name: No
        kind: variable_declarator
"#,
        );
        write_file(
            &modules.join("deferred.yaml.deferred"),
            r#"path: deferred
members:
  - name: DeferredThing
    selector:
      binding:
        name: d
        kind: function_declaration
"#,
        );
        write_file(
            &ancillary,
            r#"modules:
  - chunk_id: static/extra
    path: chunks/extra
    members:
      - name: ExtraThing
        selector:
          binding:
            name: e
            kind: import_specifier
  - chunk_id: static/skipped
    path: chunks/skipped
    members:
      - name: SkippedThing
        selector:
          binding:
            name: s
            kind: variable_declarator
"#,
        );
        CompileSpecTreeOptions {
            config_path: config,
            modules_root: modules,
            vendor_marks_path: vendor_marks,
            ancillary_modules_path: Some(ancillary),
            out_root: Some(PathBuf::from("out/override")),
        }
    }

    #[test]
    fn compiles_tree_sources_into_executable_transform_spec() {
        let temp = tempfile::tempdir().unwrap();
        let spec = compile_spec_tree(&fixture(temp.path())).unwrap();

        assert!(spec.logical_modules["static/main"].contains_key("active"));
        assert!(spec.logical_modules["static/extra"].contains_key("chunks/extra"));
        assert!(!spec.logical_modules.contains_key("static/skipped"));
        assert_eq!(
            spec.logical_modules["static/main"]["active"].members[0]
                .name
                .as_deref(),
            Some("No")
        );
        assert_eq!(
            spec.chunk_renames["static/main"].members[0].name.as_deref(),
            Some("DeferredThing")
        );
        assert_eq!(
            spec.swap_vendor_chunks
                .output_manifest_path
                .as_deref()
                .unwrap(),
            Path::new("out/override/vendors/manifest.json")
        );
        assert_eq!(spec.vendor["static/vendor.js"].identity, "example");
    }

    #[test]
    fn serialized_spec_omits_retired_and_trivial_fields() {
        let temp = tempfile::tempdir().unwrap();
        let spec = compile_spec_tree(&fixture(temp.path())).unwrap();
        let value: Value = serde_yaml::from_str(&serde_yaml::to_string(&spec).unwrap()).unwrap();

        assert!(value.get("kind").is_none());
        assert!(value.get("schema_version").is_none());
        assert!(value.get("pipeline").is_none());
        assert!(value.get("operations").is_none());
        assert!(value.get("rewrite_chunk_entry_specifiers").is_none());
        assert!(value.get("write_js_tree").is_none());
        assert!(
            value["materialize_logical_modules"]
                .get("target_dir")
                .is_none()
        );
        assert!(
            value["logical_modules"]["static/main"]["active"]["members"][0]
                .get("purity")
                .is_none()
        );
    }

    #[test]
    fn rejects_legacy_binding_kind_spelling() {
        let temp = tempfile::tempdir().unwrap();
        let options = fixture(temp.path());
        write_file(
            &options.modules_root.join("active.yaml"),
            r#"path: active
members:
  - name: Bad
    selector:
      binding:
        name: bad
        kind: FunctionDeclaration
"#,
        );

        let error = compile_spec_tree(&options).unwrap_err();
        assert!(error.to_string().contains("active.yaml"), "{error:#}");
    }

    #[test]
    fn rejects_mismatched_module_path() {
        let temp = tempfile::tempdir().unwrap();
        let options = fixture(temp.path());
        write_file(
            &options.modules_root.join("active.yaml"),
            r#"path: wrong
members: []
"#,
        );

        let error = compile_spec_tree(&options).unwrap_err();
        assert!(error.to_string().contains("declares path"), "{error:#}");
    }
}
