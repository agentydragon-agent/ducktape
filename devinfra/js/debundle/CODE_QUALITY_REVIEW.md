# Debundle Code Quality Review (2026-05-09)

Highest-impact style/design/conciseness improvements identified across `devinfra/js/debundle/`.

## Completed

- **ChunkId intern table** (`ids.rs`): `ChunkId(usize)` newtype + `ChunkTable`; eliminates
  string cloning on every chunk access. (2026-05-10)
- **`ArtifactIndexes` `BTreeMap` → `HashMap`**: All hot-path lookup maps now use `HashMap`.
  Removed dead `chunk_id_index` field and `chunk_index()` method. (2026-05-10)
- **`JsChunk.files` `BTreeMap<String, JsFile>` → `Vec<JsFile>`**: Chunks carry 1–2 files in
  practice; BTreeMap overhead was pure waste. Added `get_file` / `remove_file` / `insert_file` /
  `file_paths` helpers on `JsChunk`. (2026-05-10)
- **Extract shared `visit_class_member` helpers from 4 visitors** (`facts.rs`): collapsed the
  ~160 lines of near-identical class-member match arms into `visit_eager_member_parts`; all four
  visitors now delegate to it. (2026-05-09)
- **`EdgeReason` field-access accessors**: `statement_ordinal()` / `binding()` already use
  concise pattern matching with alternation — no verbose destructuring remains.
- **`PhaseTimings::add`** already takes `impl Into<String>`.

## Pending

### 1. Deduplicate lazy-boundary visitor methods in `facts.rs`

`LazyReadCollector` (lines 482–562) and `BindingWriteCollector` (lines 575–697) have identical
`descend_lazy` methods and identical `visit_function`, `visit_arrow_expr`, `visit_method_prop`,
`visit_getter_prop`, `visit_setter_prop` implementations. The lazy/eager boundary logic could
live in a shared trait or base visitor that delegates to a callback, eliminating ~60 lines of
structural duplication.

### 2. Unify `record_reason` between `OwnerGraph` and `ModuleDepGraph` in `graph.rs`

`graph.rs:160-172` and `graph.rs:253-266` contain identical `record_reason` methods (skip
self-edges, conditionally add edge, push reason) differing only in node type. A single generic
function `fn record_reason<N: Copy + Ord + Hash>(graph: &mut DiGraphMap<N, EdgeMetadata>, …)`
would serve both.

### 3. Decouple `RewritableSpecifierDetector` from `RuntimeSourceRewriter` in `rewrite_specifiers.rs`

Both independently match the same five AST shapes (import decl, named export, export all,
dynamic import, new Worker) with the same guard conditions. The doc comment warns they must stay
in sync. A single declarative shape descriptor consumed by both visitors would eliminate the
lockstep coupling.

### 4. Replace opaque 5-tuple sort in `collect_owner_edge_entries` (`graph.rs`)

`graph.rs:503-518` sorts by `(a.0.0, a.1.0, a.2.kind(), a.2.statement_ordinal(), a.2.binding())`
— a deeply nested unnamed 5-tuple. A `#[derive(Ord)]` sort-key struct or `sort_by_key` with
named fields would make ordering intent explicit.

### 5. Convert `binding_names` from Vec-allocating to an iterator (`binding_targets.rs`)

`binding_targets.rs:15-19` allocates a `Vec<String>` via recursive `walk_pattern`, but callers
immediately iterate and discard it. A lazy `BindingNames<'a>` iterator would avoid the
allocation.

### 6. Replace `std::iter::once(x).collect::<BTreeSet<_>>()` with `BTreeSet::from([x])`

Still present in `facts.rs` at lines ~400, 405, 420, 421 (`declaration_names`,
`collect_declared_names`). `BTreeSet::from([x])` has been available since Rust 1.56.

### 7. Consolidate `HashMap`/`HashSet` local imports in `validation.rs`

`render_cycle_summary` (line 107) and `cut_pairs_count` (line 176) use local `HashMap`/`HashSet`
imports while the rest of the crate uses `BTreeMap`/`BTreeSet`. Use the tree-based variants
throughout for consistency, or lift the imports to the top of the file.
