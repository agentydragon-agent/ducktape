//! Typed deserialisation surface for `js.ast_transform_spec` JSONC files.
//!
//! Three declarative top-level maps describe what the spec wants applied:
//!
//! - `vendor` keyed by chunk path (`"static/lib.js"` → [`VendorMark`]).
//! - `logical_modules` keyed by chunk id, then target path
//!   (`"static/app"` → `"foo/bar/baz.js"` → [`LogicalModule`]).
//! - `residual_modules` keyed by chunk id (`"static/app"` →
//!   [`ResidualModule`]). At most one residual per chunk — encoded by the
//!   map shape.
//!
//! Pipeline stages run in a fixed canonical order; each stage is either
//! always-on or gated by the contents of those maps / by the presence of a
//! per-stage config field ([`TransformSpec::write_js_tree`],
//! [`TransformSpec::emit_browser_harness`]). There is no user-supplied
//! pipeline list.
//!
//! All consumers see typed structs; nothing here returns
//! `serde_json::Value` for a known field.

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TransformSpec {
    pub inputs: LoadJsChunksArgs,

    // --- declarative data sections ---
    #[serde(default)]
    pub vendor: BTreeMap<String, VendorMark>,
    #[serde(default)]
    pub logical_modules: BTreeMap<String, BTreeMap<String, LogicalModule>>,
    #[serde(default)]
    pub residual_modules: BTreeMap<String, ResidualModule>,
    /// Per-chunk in-place renames for bindings staying in entry's
    /// body (i.e. *not* assigned to a logical module and not pulled
    /// into the explicit residual). The materializer collects these
    /// into a `binding_name -> export_name` map; the lowerer rewrites
    /// identifiers in entry's source AST during chunk lowering. No
    /// `Logical(R)` module is created for these bindings, no separate
    /// residual file is emitted, and the orphan-statement node
    /// (`ModuleId::ResidualEntry`) keeps owning the bindings — which
    /// avoids the 2-module SCC the residual-member-rename path would
    /// otherwise create when orphan stmts and residual decls
    /// interleave with side-effecting initializers.
    ///
    /// Bindings claimed by a logical module take their rename from
    /// the module plan; the `chunk_renames` entry (if any) is dropped
    /// for those.
    #[serde(default)]
    pub chunk_renames: BTreeMap<String, ChunkRenames>,

    // --- per-stage configuration ---
    /// Output configuration for `swap_vendor_chunks`. The stage runs
    /// whenever `vendor` contains any `level: swap` entries; this field
    /// only adds output paths and a `write` toggle. All inner fields
    /// have defaults, so omitting `swap_vendor_chunks` is identical to
    /// supplying an empty object.
    #[serde(default)]
    pub swap_vendor_chunks: SwapVendorChunksConfig,
    /// Configuration for `materialize_logical_modules`. The stage runs
    /// whenever `logical_modules ∪ residual_modules` is non-empty; the
    /// chunk ids it processes are exactly the union of those maps'
    /// keys. This field only carries auxiliary options.
    #[serde(default)]
    pub materialize_logical_modules: MaterializeLogicalModulesConfig,
    /// When set, persist the artifact tree to `out_dir`.
    #[serde(default)]
    pub write_js_tree: Option<WriteJsTreeConfig>,
    /// When set, emit a browser-runtime harness alongside the artifact.
    #[serde(default)]
    pub emit_browser_harness: Option<EmitBrowserHarnessConfig>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LoadJsChunksArgs {
    pub input_root: PathBuf,
    pub js_list_path: PathBuf,
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct SwapVendorChunksConfig {
    #[serde(default)]
    pub output_manifest_path: Option<PathBuf>,
    #[serde(default)]
    pub output_wrapper_dir: Option<PathBuf>,
    /// Defaults to `true` — actually write the manifest / wrapper files
    /// to disk. Set `false` for dry-run.
    #[serde(default = "default_true")]
    pub write: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MaterializeLogicalModulesConfig {
    /// Optional override for the entry-file path to read per chunk.
    /// Absent means "use the chunk's recorded entry file".
    #[serde(default)]
    pub file: Option<String>,
    /// Defaults to `true` — drop chunks outside the materialised set
    /// (the union of `logical_modules` and `residual_modules` keys)
    /// before materialising. Set `false` to keep them.
    #[serde(default = "default_true")]
    pub prune_other_chunks: bool,
    #[serde(default)]
    pub force: bool,
    #[serde(default)]
    pub report_out_dir: Option<PathBuf>,
    #[serde(default)]
    pub report_summary_path: Option<PathBuf>,
    #[serde(default)]
    pub target_dir: String,
}

impl Default for MaterializeLogicalModulesConfig {
    fn default() -> Self {
        Self {
            file: None,
            prune_other_chunks: true,
            force: false,
            report_out_dir: None,
            report_summary_path: None,
            target_dir: String::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WriteJsTreeConfig {
    pub out_dir: PathBuf,
    #[serde(default)]
    pub force: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EmitBrowserHarnessConfig {
    pub asset_summary_path: PathBuf,
    pub out_dir: PathBuf,
    pub snapshot_root: PathBuf,
    #[serde(default)]
    pub force: bool,
}

/// Container for per-chunk in-place renames; see
/// [`TransformSpec::chunk_renames`].
#[derive(Debug, Clone, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChunkRenames {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub members: Vec<Member>,
}

fn default_true() -> bool {
    true
}

// --- Vendor ---------------------------------------------------------------

/// One vendor annotation, keyed in the spec by chunk path
/// (e.g. `"static/lib.js"`). The `level` discriminator selects between
/// `suppress` / `boundary-rename` / `swap`; only `swap` requires the
/// `package`/`version`/`subpath` triple, encoded as the
/// [`VendorLevel::Swap`] variant carrying those fields.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct VendorMark {
    pub identity: String,
    #[serde(default)]
    pub role: VendorRole,
    #[serde(flatten)]
    pub level: VendorLevel,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(tag = "level", rename_all = "snake_case")]
pub enum VendorLevel {
    Suppress,
    BoundaryRename,
    Swap(SwapMark),
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SwapMark {
    pub package: String,
    pub version: String,
    pub subpath: String,
    #[serde(default)]
    pub wrapper_shape: Option<WrapperShape>,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, Default, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum VendorRole {
    #[default]
    Module,
    Worker,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum WrapperShape {
    NamedFromDefault,
    NamedFromJsonDefault,
    NamedFromModuleDefault,
}

// --- Logical / Residual modules ------------------------------------------

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LogicalModule {
    #[serde(default)]
    pub members: Vec<Member>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResidualModule {
    /// Logical-module path the residual catch-all writes to. Defaults to
    /// `"residual/unhandled"` when absent.
    #[serde(default)]
    pub target: Option<String>,
    #[serde(default)]
    pub members: Vec<Member>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Member {
    /// Public export name. Defaults to the bound `selector.binding.name`.
    #[serde(default)]
    pub name: Option<String>,
    pub selector: MemberSelector,
    #[serde(default)]
    pub purity: MemberPurity,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MemberSelector {
    pub binding: BindingSelector,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindingSelector {
    pub name: String,
    #[serde(default)]
    pub kind: Option<BindingSourceKind>,
}

#[derive(Debug, Clone, Copy, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum BindingSourceKind {
    /// The bound name comes from an `import` specifier in the source
    /// chunk, not a top-level decl. The materializer rewrites the import
    /// statement to a re-import in the destination module.
    ImportSpecifier,
    /// Top-level `var` / `let` / `const` declaration in the source chunk.
    /// Carried for documentation; no special materializer path.
    VariableDeclarator,
    /// Top-level `function` declaration in the source chunk.
    FunctionDeclaration,
    /// Top-level `class` declaration in the source chunk.
    ClassDeclaration,
}

#[derive(Debug, Clone, Copy, Deserialize, Default, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum MemberPurity {
    #[default]
    Default,
    /// Author asserts that calls to the bound function have no observable
    /// side effects. Validator drops `S` edges for `<binding>(...)` call
    /// sites. See AGENTS.md "Declared purity" + DESIGN.md A9.
    Pure,
}
