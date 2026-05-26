//! Module analysis engine for `materialize_logical_modules`.
//!
//! Background: see <DESIGN.md>. This crate treats debundling as an
//! owner-graph quotient and scheduling problem:
//!
//! 1. Analyze each source chunk into top-level owner facts: declarations,
//!    at-init reads/writes, lazy reads/writes, side effects, imports, source
//!    locations, and top-level await.
//! 2. Build a fine-grained owner graph over those facts.
//! 3. Map owners to destination modules from the spec.
//! 4. Quotient the owner graph into the module dependency graph used by ESM
//!    import emission and linker-order reasoning.
//! 5. Validate realizability and emit stable graph reports from that same
//!    graph model. Agent-facing peel recommendation heuristics run from the
//!    serialized graph via the `debundle peel` CLI.

mod atomic_units;
mod chunk_analysis;
mod chunk_factorization;
mod factor_assembly;
mod facts;
mod graph;
mod ids;
mod partition;
mod purity;
mod realizability;
mod report_schema;
mod reports;
mod rollback_graph;
mod stage_one;
mod validation;

pub use atomic_units::{
    AtomicUnit, OwnerGraphAndUnits, compute_atomic_units, compute_owner_graph_and_units,
    compute_owner_graph_and_units_with,
};
pub use chunk_analysis::ChunkAnalysis;
pub use chunk_factorization::ChunkFactorization;
pub use factor_assembly::{
    AssemblyOutcome, AtomicUnitConflict, ConflictingClaim, assemble_partition,
};
pub use facts::{
    AnalysisHints, ChunkFactAnalysis, ChunkFactsReport, EffectCell, EffectCellReport, IdReport,
    KnownEffect, LocalEffectPolicy, SCHEMA_VERSION as CHUNK_FACTS_SCHEMA_VERSION,
    StatementEffectSummary, StatementEffectSummaryReport, StatementFacts, StatementFactsReport,
    StatementKind, analyze_chunk, find_top_level_await, local_namespace_iife_target,
};
pub use graph::{
    ChunkConstrainingEdgeSet, DepKind, EdgeMetadata, EdgeReason, EdgeRole, ModuleQuotient,
    OwnerEdge, OwnerEdgeId, OwnerGraph, OwnerGraphOptions, OwnerId, OwnerNode, OwnerReportIndex,
    build_module_quotient, build_owner_graph, build_owner_graph_with,
    chunk_constraining_module_edges, chunk_linker_order, chunk_source_import_order,
};
pub use ids::{
    BindingKind, ChunkId, ChunkTable, LogicalModule, LogicalModuleIndex, ModuleId,
    StatementOrdinal, top_level_id,
};
pub use partition::Partition;
pub use purity::{
    Purity, PurityReason, PurityRule, RedundantPureMemberHint, RedundantPureMemberReason,
    RedundantPurityHint, RedundantPurityReason,
};
pub use realizability::{
    CrossRebindEdge, DeltaHandle, PartitionDelta, RealizabilityIndex, RealizabilityVerdict,
    UnrealizableScc, check_realizability,
};
pub use report_schema::{
    AtomicGraphReport, AtomicUnitEdgeReport, AtomicUnitReport, BindingReport, EdgeRoleReport,
    FactorizeDiagnosticReason, LineRange, ModuleReportRef, OwnerGraphEdgeReport,
    OwnerGraphNodeReport, OwnerGraphQuotientReport, OwnerGraphReport, PeelCandidateStatus,
    QuotientEdgeReport, QuotientSccReport, RESIDUAL_ENTRY_LABEL, RESIDUAL_ENTRY_MODULE_ID,
    SourceLocation,
};
pub use stage_one::{StageOneAnalysis, compute_stage_one_analysis};
pub use stage_one::sidecars::{
    CHUNK_ANALYSIS_MANIFEST_SCHEMA_VERSION, ChunkAnalysisManifest, write_stage_one_sidecars,
};
pub use validation::{
    CycleEdge, CycleReport, FactorizationReport, render_atomic_unit_conflict_summary,
    render_cycle_summary, validate_factorization,
};

#[cfg(test)]
mod analysis_tests;
