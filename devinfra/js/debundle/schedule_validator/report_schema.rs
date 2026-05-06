use serde::{Deserialize, Serialize};

use super::{BindingName, EdgeKind, StatementKind, StatementOrdinal};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceLocation {
    pub source_path: String,
    pub start_line: usize,
    pub end_line: usize,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub struct BindingReport {
    pub binding: BindingName,
    pub export_name: BindingName,
}

/// Node-link JSON side output for downstream graph analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphReport {
    pub chunk_id: String,
    pub nodes: Vec<OwnerGraphNodeReport>,
    pub edges: Vec<OwnerGraphEdgeReport>,
    pub quotient: OwnerGraphQuotientReport,
    pub peelability: OwnerGraphPeelabilityReport,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphNodeReport {
    pub id: String,
    pub statement_ordinal: StatementOrdinal,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_location: Option<SourceLocation>,
    pub declared_bindings: Vec<BindingReport>,
    pub statement_kind: StatementKind,
    pub has_side_effect: bool,
    pub destination: ModuleReportRef,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphEdgeReport {
    pub id: String,
    pub source: String,
    pub target: String,
    pub edge_kind: EdgeKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub binding: Option<BindingName>,
    pub statement_ordinal: StatementOrdinal,
    pub constrains_realizability: bool,
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
    pub edge_kinds: Vec<EdgeKind>,
    pub constrains_realizability: bool,
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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphPeelabilityReport {
    pub residual_destinations: Vec<ModuleReportRef>,
    pub minimal_peel_sets: Vec<OwnerGraphPeelSetReport>,
    pub residual_owner_horizon: Vec<ResidualOwnerPeelHorizonReport>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResidualOwnerPeelHorizonReport {
    pub owner_id: String,
    pub statement_ordinal: StatementOrdinal,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_location: Option<SourceLocation>,
    pub statement_kind: StatementKind,
    pub has_side_effect: bool,
    pub current_destination: ModuleReportRef,
    pub members: Vec<BindingReport>,
    pub status: ResidualOwnerPeelStatus,
    pub peel_set_ids: Vec<String>,
    pub companion_options: Vec<ResidualOwnerCompanionOptionReport>,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResidualOwnerPeelStatus {
    Direct,
    WithCompanions,
    Blocked,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResidualOwnerCompanionOptionReport {
    pub peel_set_id: String,
    pub companion_owner_ids: Vec<String>,
    pub companion_members: Vec<BindingReport>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OwnerGraphPeelSetReport {
    pub candidate_id: String,
    pub owner_set_kind: PeelCandidateKind,
    pub owner_ids: Vec<String>,
    pub members: Vec<BindingReport>,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PeelCandidateKind {
    SingleOwner,
    OwnerPair,
    OwnerClosure,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PeelCandidateStatus {
    PeelableNow,
    BlockedCycle,
    BlockedResidualDependency,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModuleReportRef {
    pub id: String,
    pub label: String,
    pub residual: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub index: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target_file: Option<String>,
}
