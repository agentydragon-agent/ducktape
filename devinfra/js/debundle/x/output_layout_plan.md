# Debundle Output Layout Migration Note

Status: completed migration note for the backward-incompatible output-layout
cutover. The tree below is the current output contract; old path names appear
only in the migration mapping and historical cleanup checklist.

The previous output tree mixed browser-loadable files, sidecar JSON outputs,
planner/debug JSON outputs, generated vendor runtime files, and runtime
metadata at the same root. The current shape uses two top-level categories:

- `app/`: browser-loadable output only.
- `reports/`: JSON side outputs for agents and tooling.

## Current Tree

This tree is intentionally representative rather than exhaustive. The example
does not list every emitted JavaScript module, but it includes every kind of
output the pipeline currently generates or is expected to generate after
directory/file modularity reports land.

```text
debundle.out/
├── app/
│   ├── index.html
│   ├── bootstrap.js
│   ├── package.json
│   ├── preload/
│   │   └── style.css
│   ├── static/
│   │   ├── index-C-TB2oZS.css
│   │   ├── Calendar-ClsfTTyA/
│   │   │   └── entry.js
│   │   ├── index-DI2GynTv/
│   │   │   ├── entry.js
│   │   │   ├── ai/
│   │   │   │   ├── streaming_phase.js
│   │   │   │   └── tooling/
│   │   │   │       └── system_tool_registry.js
│   │   │   ├── domains/
│   │   │   │   └── graph/
│   │   │   │       └── core_node_model/
│   │   │   │           └── tana_node.js
│   │   │   ├── features/
│   │   │   │   └── search/
│   │   │   │       └── search_box.js
│   │   │   └── ui/
│   │   │       └── button.js
│   │   └── vendor-BPNhzNbc/
│   │       └── entry.js
│   └── vendors/
│       └── generated/
│           └── static/
│               ├── cl100k_base-BbTNOy-H/
│               │   └── entry.js
│               └── o200k_base-CNXPGfOF/
│                   └── entry.js
└── reports/
    ├── runtime.json
    ├── output.json
    ├── chunks.json
    ├── source_assets.json
    ├── vendor_swaps.json
    ├── provenance.json
    ├── rename_queue.json
    └── tree/
        ├── index.json
        ├── static/
        │   ├── index.json
        │   ├── index-C-TB2oZS.css.json
        │   ├── Calendar-ClsfTTyA/
        │   │   ├── index.json
        │   │   ├── entry.js.json
        │   │   └── chunk.json
        │   └── index-DI2GynTv/
        │       ├── index.json
        │       ├── entry.js.json
        │       ├── chunk.json
        │       ├── owner_graph.json
        │       ├── modules.json
        │       ├── cycles.json              # emitted only on failure
        │       ├── atomic_unit_conflicts.json # emitted only on failure
        │       ├── ai/
        │       │   ├── index.json
        │       │   ├── streaming_phase.js.json
        │       │   └── tooling/
        │       │       ├── index.json
        │       │       └── system_tool_registry.js.json
        │       ├── domains/
        │       │   ├── index.json
        │       │   └── graph/
        │       │       ├── index.json
        │       │       └── core_node_model/
        │       │           ├── index.json
        │       │           └── tana_node.js.json
        │       └── features/
        │           ├── index.json
        │           └── search/
        │               ├── index.json
        │               └── search_box.js.json
        └── vendors/
            └── generated/
                └── static/
                    └── o200k_base-CNXPGfOF/
                        ├── index.json
                        ├── entry.js.json
                        └── chunk.json
```

## Placement Rules

`app/` is the runtime tree. Anything the browser may load directly belongs
there, including rewritten HTML, generated bootstrap JS, copied non-JS assets,
emitted chunk `entry.js` files, peeled module JS files, and generated vendor
replacement JS files. JSON side outputs should not live in `app/` unless the
browser truly imports them as runtime data.

`reports/` owns every non-runtime side output. The split between "manifest" and
"report" is not useful enough to preserve as directory structure; agents
consume all of these as JSON evidence. Root-level reports describe the whole
output or cross-cutting pipeline state. Tree-shaped reports live under
`reports/tree/`, mirroring paths under `app/`.

Directory, file, and chunk-scoped reports share `reports/tree/` because they are
all evidence about nodes in the emitted output tree. A directory node uses
`index.json`; a file node uses `<filename>.json`; a chunk root can also carry
chunk-scoped reports such as `chunk.json`, `owner_graph.json`,
`modules.json`, and error-only failure evidence.

Do not emit HTML report formats. The browser still needs `app/index.html`, but
source/provenance data for agents should be JSON-only. If source HTML
provenance is worth preserving, store its path/hash/metadata in
`reports/provenance.json`, not as a copied `source.html` report.

## Old-to-Current Mapping

```text
manifest.json
  -> reports/runtime.json
  -> reports/output.json

chunks.manifest.json
  -> reports/chunks.json

asset-summary.json
  -> reports/source_assets.json

SOURCE.json
  -> reports/provenance.json

source.html
  -> drop, or encode JSON metadata in reports/provenance.json

identifier-rename-queue.json
  -> reports/rename_queue.json

analysis/logical_modules/summary.json
  -> fold aggregate module counts into reports/chunks.json and reports/output.json

analysis/logical_modules/<chunk-id>/owner_graph.json
  -> reports/tree/<chunk-id>/owner_graph.json

analysis/logical_modules/<chunk-id>/logical_modules.json
  -> reports/tree/<chunk-id>/modules.json

analysis/logical_modules/<chunk-id>/factorization.json
  -> fold compact validation summary into reports/tree/<chunk-id>/chunk.json

analysis/logical_modules/<chunk-id>/cycles.json
  -> reports/tree/<chunk-id>/cycles.json, emitted only on failure

<chunk-id>/atomic unit conflict evidence
  -> reports/tree/<chunk-id>/atomic_unit_conflicts.json, emitted only on failure

static/<chunk-id>/manifest.json
  -> reports/tree/<chunk-id>/chunk.json

directory_manifests/index.json
  -> reports/tree/index.json

directory_manifests/<emitted-dir>/manifest.json
  -> reports/tree/<emitted-dir>/index.json

<emitted-file modularity report>
  -> reports/tree/<emitted-file>.json

vendors/manifest.json
  -> reports/vendor_swaps.json

vendors/vendor_partial_swap_manifest.json
  -> fold into reports/vendor_swaps.json

vendors/generated/**
  -> app/vendors/generated/**

index.html, bootstrap.js, package.json, preload/**, static/**/*.css,
static/**/*.js, and other copied non-JS runtime assets
  -> app/**
```

## Migration Notes

- Update live-proxy and browser-load tests to read `reports/runtime.json`
  and serve `app/` as the runtime root.
- Update committed JS snapshot regeneration to copy `app/static/**/*.js`
  instead of root `static/**/*.js`.
- Update `debundle peel` docs and skills to use
  `reports/tree/<chunk-id>/owner_graph.json`.
- Update architect and lane-worker skills to prefer
  `reports/tree/index.json` and mirrored tree reports for hierarchy health.
- Treat this as a contract move when implemented: update callers and tests
  together rather than adding long-lived compatibility aliases.

## Naming Cleanup

The implementation names should move with the file layout. In particular,
the per-chunk modules report is `ChunkModulesReport` and its file name is
`modules.json`.

Similarly, `FactorizationReport` is currently a validation result over the
chosen module assignment rather than a broad factorization artifact. Rename it
toward `ModuleAssignmentValidationSummary` or similar, and embed its compact
successful-run summary in `chunk.json`.

Detailed failure evidence should be sparse:

- `cycles.json` exists only when validation rejects with realizability cycles.
- `atomic_unit_conflicts.json` exists only when validation rejects because an
  atomic factor unit was split across destination modules.
- Failure detail beyond the compact `chunk.json` summary belongs in the
  error-only sibling files above.

Do not include explicit links from `chunk.json` to neighboring reports. The
layout is deterministic: consumers that know
`reports/tree/<chunk-id>/chunk.json` can derive sibling paths such as
`owner_graph.json`, `modules.json`, and failure evidence without
duplicated path fields.

The current chunk manifest's `parser` field is parse provenance, not app
structure: it records syntax mode such as source type, parser plugins, and
whether undeclared exports were tolerated. Do not make it a prominent
`chunk.json` field while these settings are static/default across chunks. If
per-chunk parser settings become meaningful, include a compact optional `parse`
summary in `chunk.json`; otherwise keep parse tool provenance in
`reports/provenance.json` or drop it.

Full and partial vendor swaps should share `reports/vendor_swaps.json`. They
are two modes of one substitution subsystem, and a single report lets agents
answer "what did we replace with package code?" without joining two root files.

## JSON Outputs And Schemas

`app/package.json` is the only runtime JSON generated by debundle:

```ts
interface RuntimePackageJson {
  type: "module";
}
```

All other generated JSON belongs under `reports/`. Runtime JSON assets copied
from the source application, if any, remain under `app/` and are not debundle
reports.

Paths in the schemas below are slash-separated. `AppPath` is relative to
`app/`. Optional fields are marked with `?`.

```ts
type AppPath = string;
type ChunkId = string;
type EdgeKind = string; // serialized DepKind, for example "eager_use"
type ModuleId = string;
type SymbolId = string;

interface OutputSize {
  files: number;
  bytes: number;
  lines: number;
}

interface OutputFraction {
  bytes: number;
  lines: number;
}

interface OutputFileMetric {
  file: AppPath;
  role: "top_level_entry" | "named_module" | "residual_module" | "other";
  bytes: number;
  lines: number;
  module_id?: ModuleId;
  module_path?: AppPath;
}

interface OutputMetrics {
  total: OutputSize;
  top_level_entry: OutputSize;
  named_modules: OutputSize;
  residual_modules: OutputSize;
  other_files: OutputSize;
  named_module_fraction: OutputFraction;
  residual_module_fraction: OutputFraction;
  top_level_entry_fraction: OutputFraction;
  largest_files_by_bytes: OutputFileMetric[];
}
```

Root reports:

```ts
// reports/runtime.json
interface RuntimeReport {
  runtime_root: "app";
  entry_scripts: AppPath[];
  module_preloads: AppPath[];
  copied_assets: AppPath[];
  generated: {
    index_html: "index.html";
    bootstrap: "bootstrap.js";
    package_json: "package.json";
  };
}

// reports/output.json
interface OutputReport {
  totals: {
    retained_entry_declaration_owners: number;
    top_level_side_effects: number;
    export_aliases: number;
    unresolved_exports: number;
  };
  output_metrics: OutputMetrics;
  module_metrics?: ModuleMetrics;
}

interface ModuleMetrics {
  total_symbols_defined: number;
  total_exported_symbols: number;
  export_ratio: number;
  loc_distribution: { p50: number; p90: number; max: number; min: number };
  entropy: number;
}

// reports/chunks.json
interface ChunksReport {
  chunks: Array<{
    chunk_id: ChunkId;
    source_chunk_path: string;
    entry_path: AppPath;
    dir: AppPath;
    modules: ModuleId[];
  }>;
}

// reports/source_assets.json
interface SourceAssetsReport {
  ui_version?: string;
  snapshot_path?: string;
  counts: Record<string, number>;
  entry_points: { html: string[]; js: string[]; css: string[] };
  sizes?: Record<string, number>;
  largest_js?: unknown[];
  largest_css?: unknown[];
  formatter?: unknown;
}

// reports/provenance.json
interface ProvenanceReport {
  source?: unknown; // normalized SOURCE.json content, if present
  source_html?: { path: string; sha256?: string; bytes?: number };
  parser_defaults?: ParseOptions;
  debundle?: { version?: string; git_commit?: string };
}

interface ParseOptions {
  source_type: "module" | string;
  plugins: string[];
  allow_undeclared_exports: boolean;
}
```

Vendor and rename reports:

```ts
// reports/vendor_swaps.json
interface VendorSwapsReport {
  full: Record<string, FullVendorSwapResolution>; // keyed by source chunk path
  partial: Record<string, PartialVendorSwapResolution>; // keyed by source chunk path
  strip_stats?: Record<string, ChunkStripStats>;
}

interface FullVendorSwapResolution {
  chunk_id: ChunkId;
  chunk_path: string;
  entry_path: AppPath;
  package: string;
  version: string;
  subpath: string;
  wrapper_shape?: unknown;
  generated_wrapper_path?: AppPath;
}

interface PartialVendorSwapResolution {
  chunk_id: ChunkId;
  chunk_path: string;
  packages: Record<string, { namespace?: string; version: string; subpath: string }>;
  symbols: Record<
    string,
    {
      package: string;
      kind: "member" | "namespace" | "default" | "named";
      upstream_export?: string;
      references_rewritten: number;
    }
  >;
}

interface ChunkStripStats {
  chunk_path: string;
  stripped_export_specifiers: number;
  dropped_top_level_items: number;
  retained_top_level_items: number;
}

// reports/rename_queue.json
interface RenameQueueReport {
  entries: Array<{
    selector: string;
    name: string;
    ref_count: number;
    fanout_modules: number;
    owner_chunk: ChunkId;
    owner_file: AppPath;
  }>;
}
```

Tree reports:

```ts
// reports/tree/index.json and reports/tree/**/index.json
interface DirectoryReport {
  path: AppPath; // "" for reports/tree/index.json, otherwise app-relative
  directories: AppPath[];
  files: AppPath[];
  chunks: ChunkId[];
  modules: ModuleId[];
  defined_symbols: SymbolId[];
  loc: number;
  incoming: DirectionalSummary;
  outgoing: DirectionalSummary;
  incoming_edges: DirectoryDependencyEdge[];
  outgoing_edges: DirectoryDependencyEdge[];
}

interface DirectionalSummary {
  edge_count_by_kind: Record<EdgeKind, number>;
  symbols: Record<SymbolId, number>;
  files: Record<AppPath, number>;
}

interface DirectoryDependencyEdge {
  source_dir: AppPath;
  target_dir: AppPath;
  edge_count_by_kind: Record<EdgeKind, number>;
  symbols: Record<SymbolId, number>;
  source_files: Record<AppPath, number>;
  target_files: Record<AppPath, number>;
}

// reports/tree/**/*.js.json and reports/tree/**/*.css.json
interface FileReport {
  path: AppPath;
  role: "top_level_entry" | "named_module" | "residual_module" | "other";
  bytes: number;
  lines: number;
  chunk_id?: ChunkId;
  module_id?: ModuleId;
  module_path?: AppPath;
  defined_symbols?: SymbolId[];
  incoming?: DirectionalSummary;
  outgoing?: DirectionalSummary;
}
```

For directory reports, "incoming" and "outgoing" deliberately exclude uses where
both endpoint files are inside that directory. For file reports, "incoming" and
"outgoing" exclude self-uses. Non-JS asset file reports can omit symbol and
dependency fields.

Chunk reports:

```ts
// reports/tree/<chunk-id>/chunk.json
interface ChunkReport {
  chunk_id: ChunkId;
  source_chunk_path: string;
  entry_path: AppPath;
  counts: ChunkCounts;
  files: Array<{ path: AppPath; role: "entry" | "module" | "runtime" }>;
  imports: ImportRecord[];
  export_aliases: ExportAliasRecord[];
  unresolved_exports: ExportAliasRecord[];
  retained_entry_declarations: RetainedEntryDeclaration[];
  modules?: { ids: ModuleId[]; dir: AppPath };
  output_metrics: OutputMetrics;
  validation: ModuleAssignmentValidationSummary;
  parse?: ParseOptions;
}

interface ChunkCounts {
  dynamic_imports: number;
  top_level_bindings: number;
  top_level_declaration_owners: number;
  top_level_side_effects: number;
}

interface ModuleAssignmentValidationSummary {
  status: "ok" | "failed";
  linker_order: ModuleId[];
}

interface ImportRecord {
  id: string;
  line?: number;
  source: string;
  specifiers: Array<{
    kind: "named" | "default" | "namespace";
    imported?: string;
    local: string;
    source?: string;
  }>;
}

interface ExportAliasRecord {
  exported: string;
  line?: number;
  local?: string;
}

interface RetainedEntryDeclaration {
  id: string;
  line?: number;
  names: string[];
  declaration_kind: "function" | "class" | "variable";
  reason: string;
}

// reports/tree/<chunk-id>/owner_graph.json
interface OwnerGraphReport {
  chunk_id: ChunkId;
  nodes: OwnerGraphNode[];
  edges: OwnerGraphEdge[];
  module_graph: {
    nodes: ModuleRef[];
    edges: Array<{
      id: string;
      source: ModuleId;
      target: ModuleId;
      edge_kinds: EdgeKind[];
      constrains_init_order: boolean;
    }>;
    sccs: Array<{
      id: string;
      modules: ModuleId[];
      labels: string[];
      is_cycle: boolean;
      realizable: boolean;
      module_edge_ids: string[];
      constraining_module_edge_ids: string[];
    }>;
  };
  peelability: unknown; // existing OwnerGraphPeelabilityReport shape
  peel_proposals: unknown; // existing FactorizeReport shape, renamed at the JSON boundary
}

interface OwnerGraphNode {
  id: string;
  statement_ordinal: number;
  source_location?: { source_path: string; start_line: number; end_line: number };
  declared_bindings: Array<{ binding: string; export_name: string }>;
  statement_kind: string;
  purity: unknown;
  destination: ModuleRef;
}

interface OwnerGraphEdge {
  id: string;
  source: string;
  target: string;
  edge_kind: EdgeKind;
  binding?: string;
  statement_ordinal: number;
  constrains_init_order: boolean;
}

interface ModuleRef {
  id: ModuleId;
  label: string;
  residual: boolean;
  index?: number;
  file_path?: AppPath;
}

// reports/tree/<chunk-id>/modules.json
interface ChunkModulesReport {
  chunk_id: ChunkId;
  modules: Array<{
    id: ModuleId;
    module_path: AppPath;
    file_path: AppPath;
    residual: boolean;
    owner_ids: string[];
    input_bindings: string[];
    exports: string[];
  }>;
  requested: Array<{ id: ModuleId; module_path: AppPath; residual: boolean }>;
  redundant_purity_hints?: unknown[];
}
```

Failure-only reports:

```ts
// reports/tree/<chunk-id>/cycles.json, emitted only when there are cycles
interface CyclesReport {
  chunk_id: ChunkId;
  cycles: Array<{
    modules: ModuleId[];
    evidence: CycleEdge[];
    cut: CycleEdge[];
  }>;
}

interface CycleEdge {
  from: ModuleId;
  to: ModuleId;
  statement_ordinal: number;
  binding?: string;
  edge_kind: EdgeKind;
}

// reports/tree/<chunk-id>/atomic_unit_conflicts.json,
// emitted only when there are atomic unit conflicts
interface AtomicUnitConflictsReport {
  chunk_id: ChunkId;
  conflicts: Array<{
    members: string[];
    claims: Array<{ owner: string; bindings: string[]; module: ModuleId }>;
    causes: EdgeKind[];
  }>;
}
```

There is no `validation.json`; compact validation status lives in `chunk.json`,
with detailed failure evidence split into the sparse failure-only reports. There
are no path links from one report JSON file to neighboring report JSON files.

## Historical Migration Checklist

This was a backward-incompatible cutover. It intentionally did not add old-path
aliases, dual manifests, compatibility readers, or deprecation shims. The
cutover landed as one coherent Ducktape change, followed by a Gaffer repin that
updated the consuming Tana targets to the new contract.

The checklist below is retained as implementation history.

### 1. Freeze The Contract

- This file was the provisional source of truth while implementing.
- Final names and fields were reconciled here before the cutover landed.
- Focused tests assert the new output tree shape, especially absence
  of old roots such as `analysis/`, `directory_manifests/`,
  `identifier-rename-queue.json`, top-level `manifest.json`,
  `chunks.manifest.json`, and `vendors/`.

### 2. Centralize Layout Paths

- Added a small output-layout helper used by `emit_harness`, `write_tree`,
  `spec_tree`, `materialize_logical_modules`, vendor swap output, directory
  reports, and identifier rename queue output.
- The helper exposes semantic paths such as runtime root, reports root,
  tree reports root, chunk report directory, vendor swap report, and rename
  queue report.
- It avoids scattering string literals for `app/`, `reports/`, `reports/tree/`,
  `chunk.json`, `modules.json`, and `owner_graph.json`.

### 3. Move Runtime Output

- Browser-loadable output lands under `app/`.
- Generated HTML/bootstrap paths and module specifier rewriting were updated so
  the app still loads from `app/` as its runtime root.
- Generated vendor wrapper JS lives under `app/vendors/generated/**`.
- `app/package.json` remains runtime package metadata.

### 4. Move Root Reports

- Split the old root `manifest.json` into `reports/runtime.json` and
  `reports/output.json`.
- Rename/cut over `chunks.manifest.json` to `reports/chunks.json`.
- Rename/cut over `asset-summary.json` to `reports/source_assets.json`.
- Move `SOURCE.json` and any source HTML provenance into
  `reports/provenance.json`.
- Move `identifier-rename-queue.json` to `reports/rename_queue.json` and drop
  `generated_at_iso`.
- Merge full and partial vendor swap reports into `reports/vendor_swaps.json`.

### 5. Move Tree Reports

- Move directory reports from `directory_manifests/**/manifest.json` to
  `reports/tree/**/index.json`.
- Move per-file modularity reports to `reports/tree/<app-file>.json`.
- Move per-chunk reports to `reports/tree/<chunk-id>/`.
- Rename per-chunk `manifest.json` to `chunk.json`.
- Rename per-chunk `logical_modules.json` to `modules.json`.
- Fold compact validation state from `factorization.json` into `chunk.json`.
- Emit `cycles.json` and `atomic_unit_conflicts.json` only when the relevant
  failure evidence exists.

### 6. Rename Report Structs

- Rename the old logical-module report type toward `ChunkModulesReport`.
- Rename the broad `FactorizationReport` role toward a compact
  `ModuleAssignmentValidationSummary` embedded in `ChunkReport`.
- Rename JSON-facing fields that leak implementation terms:
  `quotient` to `module_graph`, `factorize` to `peel_proposals`,
  `selected_module_lowerings` to data in `modules.json`, and
  `kept_top_level_*` to `retained_entry_*`.
- Remove mirror length fields when the array/map being counted is in the same
  file.

### 7. Update Ducktape Consumers

- Update Rust unit/e2e tests that read old report paths:
  `pipeline.rs`, `realizability_test.rs`, vendor swap tests, identifier queue
  tests, directory report tests, and owner-graph peel/factorize tests.
- Update CLI/help text and diagnostics that mention old paths, especially
  materializer error messages and `debundle peel` examples.
- Update `DESIGN.md`, `README.md`, `TODO.md`, and `x/` notes that describe the
  emitted tree.
- Update debundle skills and shared skill docs:
  `debundle_user_guide.md`, `workflow.md`, `module_shape.md`,
  `debundle_architect`, `debundle_plan_work`, `debundle_lane_worker`,
  `debundle_intake`, `debundle_integrator`, `debundle_orchestrator`, and
  `debundle_mint_names`.
- Keep docs generic: no Tana-specific paths in Ducktape public docs or skills.

### 8. Ducktape Validation

- Run the focused debundle tests first while iterating.
- Before committing Ducktape, run the full debundle and skill validation suite:
  `nix develop --command bazelisk test //devinfra/js/debundle:cli_test
//devinfra/js/debundle:peel_test //devinfra/js/debundle:pipeline_test
//devinfra/js/debundle/e2e:all //devinfra/js/debundle/skills/...
//skills:test_frontmatter`
- Build the packaged skills tar:
  `nix develop --command bazelisk build //skills:all_skills_tar
--remote_download_outputs=all`.

### 9. Gaffer Repin And Consumer Cutover

- Commit and push Ducktape first.
- Repin Gaffer to the new Ducktape revision, updating both `MODULE.bazel` and
  `flake.lock` when they change.
- Update Tana-specific spec targets, live proxy, load tests, generated snapshot
  copy logic, and project-local agent/context docs to the new paths.
- Do not commit `reports/` snapshots unless the repo policy changes; committed
  generated JS snapshots should follow the runtime `app/` tree only.
- Validate the consumer corpus with the web and desktop debundle targets, then
  the browser/live-proxy load target.

### 10. Cleanup Gate

- Search Ducktape and Gaffer for old path strings after the repin:
  `analysis/logical_modules`, `directory_manifests`,
  `identifier-rename-queue.json`, `chunks.manifest.json`,
  `asset-summary.json`, `vendors/manifest.json`, and
  `vendor_partial_swap_manifest.json`.
- Any remaining hit must be either a historical note explicitly marked as such
  or removed/rewritten.
