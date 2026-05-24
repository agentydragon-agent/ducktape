use serde::{Deserialize, Serialize};
use swc_atoms::Atom;

use crate::purity::Purity;
use crate::{DepKind, StatementKind, StatementOrdinal};

#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct SourceLocation {
    pub source_path: String,
    pub start_line: usize,
    pub end_line: usize,
}

impl SourceLocation {
    /// Expand this location's line range to include `other`.
    pub fn expand_to(&mut self, other: &SourceLocation) {
        self.start_line = self.start_line.min(other.start_line);
        self.end_line = self.end_line.max(other.end_line);
    }
}

/// Accumulates the minimum start-line and maximum end-line across a
/// collection of `SourceLocation`s. Used to compute the
/// `source_line_range` field of `AtomicUnitReport` and similar.
pub struct LineRange {
    start: usize,
    end: usize,
    size_estimate: usize,
    found: bool,
}

impl Default for LineRange {
    fn default() -> Self {
        Self::new()
    }
}

impl LineRange {
    pub fn new() -> Self {
        Self {
            start: usize::MAX,
            end: 0,
            size_estimate: 0,
            found: false,
        }
    }

    pub fn expand(&mut self, location: &SourceLocation) {
        self.found = true;
        self.start = self.start.min(location.start_line);
        self.end = self.end.max(location.end_line);
        self.size_estimate += location.end_line + 1 - location.start_line;
    }

    pub fn size_estimate(&self) -> usize {
        self.size_estimate
    }

    pub fn into_array(self) -> Option<[usize; 2]> {
        self.found.then_some([self.start, self.end])
    }
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub struct BindingReport {
    pub binding: Atom,
    pub export_name: Atom,
}

/// Node-link JSON side output for downstream graph analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphReport {
    pub chunk_id: String,
    pub nodes: Vec<OwnerGraphNodeReport>,
    pub edges: Vec<OwnerGraphEdgeReport>,
    #[serde(rename = "module_graph")]
    pub quotient: OwnerGraphQuotientReport,
    pub atomic_graph: AtomicGraphReport,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphNodeReport {
    pub id: String,
    pub statement_ordinal: StatementOrdinal,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_location: Option<SourceLocation>,
    pub declared_bindings: Vec<BindingReport>,
    pub statement_kind: StatementKind,
    /// At-init purity classification, with structured reasons on
    /// any non-`Pure` verdict. Replaces the legacy
    /// `has_purity: bool` — consumers that want the boolean
    /// can use `purity.kind == "pure"`.
    pub purity: Purity,
    pub destination: ModuleReportRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphEdgeReport {
    pub id: String,
    pub source: String,
    pub target: String,
    pub edge_kind: DepKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub binding: Option<Atom>,
    pub statement_ordinal: StatementOrdinal,
    pub constrains_init_order: bool,
    /// Owner id (e.g. `"owner:42"`) of the at-init callee whose body
    /// produced this edge. `Some(...)` iff the edge was emitted by
    /// `graph::promote_at_init_calls`; mirrors
    /// `EdgeReason::at_init_callee_owner` through the wire format so
    /// the peel planner's `from_report` can reapply the same
    /// cross-module at-init promotion filter the materializer's gate
    /// does. See `EdgeReason::at_init_callee_owner` for the ESM-
    /// semantics justification.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub at_init_callee_owner: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphQuotientReport {
    pub nodes: Vec<ModuleReportRef>,
    pub edges: Vec<QuotientEdgeReport>,
    pub sccs: Vec<QuotientSccReport>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuotientEdgeReport {
    pub id: String,
    pub source: String,
    pub target: String,
    pub edge_kinds: Vec<DepKind>,
    pub constrains_init_order: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QuotientSccReport {
    pub id: String,
    pub modules: Vec<String>,
    pub labels: Vec<String>,
    pub is_cycle: bool,
    pub realizable: bool,
    pub module_edge_ids: Vec<String>,
    pub constraining_module_edge_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AtomicGraphReport {
    pub nodes: Vec<AtomicUnitReport>,
    pub edges: Vec<AtomicUnitEdgeReport>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AtomicUnitReport {
    pub id: String,
    pub owner_ids: Vec<String>,
    pub members: Vec<BindingReport>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub anonymous_statement_owner_ids: Vec<String>,
    pub destinations: Vec<ModuleReportRef>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub causes: Vec<DepKind>,
    pub size_lines_estimate: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_line_range: Option<[usize; 2]>,
    pub ordinal_span: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AtomicUnitEdgeReport {
    pub id: String,
    pub source: String,
    pub target: String,
    pub edge_kinds: Vec<DepKind>,
    pub owner_edge_ids: Vec<String>,
    pub constrains_init_order: bool,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PeelCandidateStatus {
    PeelableNow,
    BlockedCycle,
    BlockedResidualDependency,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[serde(rename_all = "snake_case")]
pub enum FactorizeDiagnosticReason {
    ExceedsSizeCap,
    NoExactRepair,
    ActiveModuleConflict,
    RepeatedFrontier,
}

/// Conventional JSON-key value for the residual catch-all module
/// across the report schema and downstream consumers. Kept as an SSOT
/// constant so consumers that key off "the residual module" by id can
/// still pattern-match — but the
/// debundler itself stopped using it as a discriminator: residual is
/// just a `ModuleReportRef` whose `residual: bool` flag is `true`,
/// and the synthesized module's id is `module_key(ModuleId)` (e.g.
/// `logical:7`).
pub const RESIDUAL_ENTRY_MODULE_ID: &str = "residual";

/// Conventional human-facing label some downstream tooling still
/// renders for the residual catch-all module. Production reports now
/// emit the synthesized residual logical module's own id (e.g.
/// `<chunk>::residual`); this constant remains for fixture
/// helpers that need a fallback label.
pub const RESIDUAL_ENTRY_LABEL: &str = "<residual_entry>";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModuleReportRef {
    pub id: String,
    pub label: String,
    pub residual: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub index: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_file: Option<String>,
}
