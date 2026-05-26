//! Wire-format mirror types for per-chunk static facts.
//!
//! Stage A of the per-chunk pipeline (see docs/lessons_learned/cross_process_stage_b.md and docs/design.md
//! §"Pipeline split (Stage A / Stage B)") needs to ship the full per-
//! statement facts to disk as a sidecar artifact so a separate Stage B
//! action can read them back without re-parsing the chunk. The native
//! `StatementFacts` type carries `Id = (Atom, SyntaxContext)` and other
//! swc types whose direct serde representation is opaque, so this module
//! defines a sibling wire schema we control end-to-end and a pair of
//! conversion functions between them.
//!
//! Invariants:
//! - **Round-trip equality.** `StatementFacts → StatementFactsReport →
//!   StatementFacts` produces a value equivalent to the original on every
//!   field consumed by downstream code (owner-graph build, realizability,
//!   lowering). See `facts_round_trip_unit` and the test module below.
//! - **Lossless v1.** Every field of `StatementFacts` is mirrored — nothing
//!   is dropped. Future shape changes that intentionally trade lossiness
//!   for size should bump `SCHEMA_VERSION` and document the change here.
//! - **Schema versioning.** The top-level wire envelope carries an explicit
//!   `schema_version: u32`. Bump it whenever the on-disk shape changes in a
//!   way that older readers can't accept.
//!
//! Naming convention follows `reports/schema.rs`: each `XxxReport`
//! is the wire mirror of `Xxx`, with `to_wire()` / `from_wire()`
//! pairs hung off the original types.
//!
//! # Scope: in-process debug artifact only
//!
//! `IdReport` carries `ctxt: u32` (a `SyntaxContext`'s raw value),
//! which is meaningful only within the SWC `Globals` instance that
//! allocated it. Unlike `owner_graph.json` / `cycles.json` /
//! `atomic_unit_conflicts.json` (Atom-only, cross-process safe),
//! `facts.json` is **not** cross-process portable.
//!
//! That's by design. `StatementFacts` is *pre-filter* analyzer
//! output: it includes closure-local reads carrying inner-scope
//! contexts. The downstream `binding_owner.get(binding)` filter at
//! `graph.rs:598` uses the `ctxt` to distinguish a closure-local
//! `counter` from a shadowed top-level `counter` and drops the
//! former. Stripping `ctxt` and reconstructing via `top_level_id`
//! in a separate process would produce **spurious at-init edges**
//! on every closure-local shadow of a top-level binding name
//! (worked example in `WIRE_FORMAT.md`).
//!
//! Consequence: `facts.json` is an **in-process debug artifact** —
//! humans inspecting it during a materializer run, same-process
//! CLI tools (none in flight). Separate-process consumers (the
//! `peel` family, future `binding describe` / top-level `scc` /
//! `cluster` / `binding show-code` CLIs) read `owner_graph.json`
//! and friends, which are Atom-only and post-filter.
//!
//! No cross-process materializer reader is planned. See
//! `WIRE_FORMAT.md` §"Cross-process scope: not a goal" for the
//! full reasoning and rejected alternatives.

use std::collections::BTreeSet;

use serde::{Deserialize, Serialize};
use swc_atoms::Atom;
use swc_common::SyntaxContext;
use swc_ecma_ast::Id;

use crate::purity::Purity;
use crate::{
    ChunkFactAnalysis, EffectCell, RedundantPureMemberHint, RedundantPurityHint, SourceLocation,
    StatementEffectSummary, StatementFacts, StatementKind, StatementOrdinal,
};

/// Current schema version of the chunk-facts wire format. Bump whenever
/// the on-disk shape of `ChunkFactsReport` (or any nested type) changes
/// in a way that older readers can't accept.
pub const SCHEMA_VERSION: u32 = 1;

/// Wire mirror of `Id = (Atom, SyntaxContext)`. SyntaxContext is a `u32`
/// newtype with a `#[serde(transparent)]` impl, but we round-trip via the
/// `u32` value explicitly so the on-disk shape is stable even if swc
/// ever changes SyntaxContext's serde representation.
#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub struct IdReport {
    pub name: Atom,
    pub ctxt: u32,
}

impl IdReport {
    pub fn from_id(id: &Id) -> Self {
        Self {
            name: id.0.clone(),
            ctxt: id.1.as_u32(),
        }
    }

    pub fn to_id(&self) -> Id {
        (self.name.clone(), SyntaxContext::from_u32(self.ctxt))
    }
}

/// Wire mirror of `EffectCell`. Externally-tagged enum so the JSON shape
/// stays self-describing — the wire format does not need to be compact;
/// readability and stability win over byte count.
#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum EffectCellReport {
    Binding { id: IdReport },
    GlobalProp { key: String },
}

impl EffectCellReport {
    pub fn from_cell(cell: &EffectCell) -> Self {
        match cell {
            EffectCell::Binding(id) => EffectCellReport::Binding {
                id: IdReport::from_id(id),
            },
            EffectCell::GlobalProp(key) => EffectCellReport::GlobalProp { key: key.clone() },
        }
    }

    pub fn to_cell(&self) -> EffectCell {
        match self {
            EffectCellReport::Binding { id } => EffectCell::Binding(id.to_id()),
            EffectCellReport::GlobalProp { key } => EffectCell::GlobalProp(key.clone()),
        }
    }
}

/// Wire mirror of `StatementEffectSummary`.
#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct StatementEffectSummaryReport {
    pub writes: Vec<EffectCellReport>,
    pub reads: Vec<EffectCellReport>,
    pub dataflow_summarizable: bool,
}

impl StatementEffectSummaryReport {
    pub fn from_summary(summary: &StatementEffectSummary) -> Self {
        Self {
            writes: summary
                .writes
                .iter()
                .map(EffectCellReport::from_cell)
                .collect(),
            reads: summary
                .reads
                .iter()
                .map(EffectCellReport::from_cell)
                .collect(),
            dataflow_summarizable: summary.dataflow_summarizable,
        }
    }

    pub fn to_summary(&self) -> StatementEffectSummary {
        StatementEffectSummary {
            writes: self.writes.iter().map(EffectCellReport::to_cell).collect(),
            reads: self.reads.iter().map(EffectCellReport::to_cell).collect(),
            dataflow_summarizable: self.dataflow_summarizable,
        }
    }
}

/// Wire mirror of `StatementFacts`. Field-by-field 1:1 with the native
/// type — see `facts/mod.rs` for the per-field invariants.
///
/// `Id` sets are mirrored as `Vec<IdReport>` (in `BTreeSet` iteration
/// order); the reverse conversion re-collects into a `BTreeSet`, so set
/// semantics are preserved regardless of the on-disk order. The
/// `BTreeSet` iteration order is deterministic, which keeps the JSON
/// output stable across runs and helps text-diff review.
#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct StatementFactsReport {
    pub ordinal: StatementOrdinal,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source_location: Option<SourceLocation>,
    pub declared: Vec<IdReport>,
    pub eager_reads: Vec<IdReport>,
    pub eager_rebinds: Vec<IdReport>,
    pub lazy_reads: Vec<IdReport>,
    pub lazy_rebinds: Vec<IdReport>,
    pub first_order_lazy_reads: Vec<IdReport>,
    pub first_order_lazy_rebinds: Vec<IdReport>,
    pub local_effects: Vec<IdReport>,
    pub at_init_calls: Vec<IdReport>,
    pub body_calls: Vec<IdReport>,
    pub first_order_body_calls: Vec<IdReport>,
    pub effects: StatementEffectSummaryReport,
    pub purity: Purity,
    pub kind: StatementKind,
}

impl StatementFactsReport {
    pub fn from_facts(facts: &StatementFacts) -> Self {
        Self {
            ordinal: facts.ordinal,
            source_location: facts.source_location.clone(),
            declared: ids_to_wire(&facts.declared),
            eager_reads: ids_to_wire(&facts.eager_reads),
            eager_rebinds: ids_to_wire(&facts.eager_rebinds),
            lazy_reads: ids_to_wire(&facts.lazy_reads),
            lazy_rebinds: ids_to_wire(&facts.lazy_rebinds),
            first_order_lazy_reads: ids_to_wire(&facts.first_order_lazy_reads),
            first_order_lazy_rebinds: ids_to_wire(&facts.first_order_lazy_rebinds),
            local_effects: ids_to_wire(&facts.local_effects),
            at_init_calls: ids_to_wire(&facts.at_init_calls),
            body_calls: ids_to_wire(&facts.body_calls),
            first_order_body_calls: ids_to_wire(&facts.first_order_body_calls),
            effects: StatementEffectSummaryReport::from_summary(&facts.effects),
            purity: facts.purity.clone(),
            kind: facts.kind,
        }
    }

    pub fn to_facts(&self) -> StatementFacts {
        StatementFacts {
            ordinal: self.ordinal,
            source_location: self.source_location.clone(),
            declared: ids_from_wire(&self.declared),
            eager_reads: ids_from_wire(&self.eager_reads),
            eager_rebinds: ids_from_wire(&self.eager_rebinds),
            lazy_reads: ids_from_wire(&self.lazy_reads),
            lazy_rebinds: ids_from_wire(&self.lazy_rebinds),
            first_order_lazy_reads: ids_from_wire(&self.first_order_lazy_reads),
            first_order_lazy_rebinds: ids_from_wire(&self.first_order_lazy_rebinds),
            local_effects: ids_from_wire(&self.local_effects),
            at_init_calls: ids_from_wire(&self.at_init_calls),
            body_calls: ids_from_wire(&self.body_calls),
            first_order_body_calls: ids_from_wire(&self.first_order_body_calls),
            effects: self.effects.to_summary(),
            purity: self.purity.clone(),
            kind: self.kind,
        }
    }
}

/// Top-level chunk-facts wire envelope. Carries `schema_version` at the
/// top so future shape changes can be detected, and a list of per-
/// statement records. Also mirrors the chunk-wide fields of
/// `ChunkFactAnalysis` (top-level await, redundant-hint diagnostics) so
/// a single artifact captures everything Stage B needs.
#[derive(Debug, Clone, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChunkFactsReport {
    pub schema_version: u32,
    pub facts: Vec<StatementFactsReport>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub top_level_await: Option<StatementOrdinal>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub redundant_purity_hints: Vec<RedundantPurityHint>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub redundant_pure_member_hints: Vec<RedundantPureMemberHint>,
}

impl ChunkFactsReport {
    pub fn from_analysis(analysis: &ChunkFactAnalysis) -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            facts: analysis
                .facts
                .iter()
                .map(StatementFactsReport::from_facts)
                .collect(),
            top_level_await: analysis.top_level_await,
            redundant_purity_hints: analysis.redundant_purity_hints.clone(),
            redundant_pure_member_hints: analysis.redundant_pure_member_hints.clone(),
        }
    }

    pub fn to_analysis(&self) -> ChunkFactAnalysis {
        ChunkFactAnalysis {
            facts: self
                .facts
                .iter()
                .map(StatementFactsReport::to_facts)
                .collect(),
            top_level_await: self.top_level_await,
            redundant_purity_hints: self.redundant_purity_hints.clone(),
            redundant_pure_member_hints: self.redundant_pure_member_hints.clone(),
        }
    }
}

fn ids_to_wire(set: &BTreeSet<Id>) -> Vec<IdReport> {
    set.iter().map(IdReport::from_id).collect()
}

fn ids_from_wire(list: &[IdReport]) -> BTreeSet<Id> {
    list.iter().map(IdReport::to_id).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AnalysisHints;
    use crate::facts::analyze_chunk;

    use swc_common::{FileName, SourceMap, sync::Lrc};
    use swc_ecma_ast::Module;
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

    /// Parse helper mirrors `stage_one/mod.rs::tests::parse`.
    fn parse(source: &str) -> Module {
        let cm: Lrc<SourceMap> = Default::default();
        let fm = cm.new_source_file(
            FileName::Custom("test.js".into()).into(),
            source.to_string(),
        );
        let lexer = Lexer::new(
            Syntax::Es(Default::default()),
            Default::default(),
            StringInput::from(&*fm),
            None,
        );
        Parser::new_from(lexer)
            .parse_module()
            .expect("parse module")
    }

    /// Two-way equality helper for `StatementFacts`. `StatementFacts`
    /// does not implement `PartialEq` (some inner types' equality is
    /// nontrivial and not relevant for soundness — e.g. `Purity` reasons
    /// carry an SWC `Span` that's `#[serde(skip)]` and reconstructs to
    /// `Span::default()` on the deserialize side, but `PurityReason`
    /// itself derives `PartialEq` over `span` too). The wire format
    /// elides spans on PurityReason already; here we compare the
    /// fields that the downstream owner-graph build / realizability /
    /// lowering passes actually read.
    fn facts_equiv(a: &StatementFacts, b: &StatementFacts) {
        assert_eq!(a.ordinal, b.ordinal, "ordinal");
        assert_eq!(a.source_location, b.source_location, "source_location");
        assert_eq!(a.declared, b.declared, "declared");
        assert_eq!(a.eager_reads, b.eager_reads, "eager_reads");
        assert_eq!(a.eager_rebinds, b.eager_rebinds, "eager_rebinds");
        assert_eq!(a.lazy_reads, b.lazy_reads, "lazy_reads");
        assert_eq!(a.lazy_rebinds, b.lazy_rebinds, "lazy_rebinds");
        assert_eq!(
            a.first_order_lazy_reads, b.first_order_lazy_reads,
            "first_order_lazy_reads"
        );
        assert_eq!(
            a.first_order_lazy_rebinds, b.first_order_lazy_rebinds,
            "first_order_lazy_rebinds"
        );
        assert_eq!(a.local_effects, b.local_effects, "local_effects");
        assert_eq!(a.at_init_calls, b.at_init_calls, "at_init_calls");
        assert_eq!(a.body_calls, b.body_calls, "body_calls");
        assert_eq!(
            a.first_order_body_calls, b.first_order_body_calls,
            "first_order_body_calls"
        );
        assert_eq!(a.effects.writes, b.effects.writes, "effects.writes");
        assert_eq!(a.effects.reads, b.effects.reads, "effects.reads");
        assert_eq!(
            a.effects.dataflow_summarizable, b.effects.dataflow_summarizable,
            "effects.dataflow_summarizable"
        );
        // `Purity` derives `PartialEq`; that covers `kind`, the `reasons`
        // vec, `rule`, `source_location`, `detail`, and (since `Span`
        // is `#[serde(skip)]` and reconstructs to default on the
        // deserialize side) we compare spans in both `a` and `b` after
        // they've gone through the same skip-and-default cycle when
        // applicable. In the round-trip test below we only push the
        // round-tripped value through serde, so `b.purity.reasons[*].span`
        // is `Span::default()`. We sidestep that by comparing structural
        // fields explicitly.
        assert_eq!(a.purity.is_pure(), b.purity.is_pure(), "purity.is_pure");
        if let (Purity::NotPure { reasons: ra }, Purity::NotPure { reasons: rb }) =
            (&a.purity, &b.purity)
        {
            assert_eq!(ra.len(), rb.len(), "purity reason count");
            for (i, (ria, rib)) in ra.iter().zip(rb.iter()).enumerate() {
                assert_eq!(ria.rule, rib.rule, "reason[{i}].rule");
                assert_eq!(
                    ria.source_location, rib.source_location,
                    "reason[{i}].source_location",
                );
                assert_eq!(ria.detail, rib.detail, "reason[{i}].detail");
                // span deliberately skipped — it's `#[serde(skip)]`.
            }
        }
        assert_eq!(a.kind, b.kind, "kind");
    }

    /// Full JSON round-trip on a chunk that touches every fact bucket:
    /// declared bindings, eager reads, lazy reads (function body), at-
    /// init calls, body calls, exports, a side-effect statement, a
    /// global-prop write (triggers `EffectCell::GlobalProp`), and a
    /// non-pure side-effect statement (so the wire format exercises
    /// `Purity::NotPure` reasons).
    #[test]
    fn round_trip_via_json_preserves_every_fact_field() {
        let src = "\
const A = 1;
function f() { return A + g(); }
function g() { return 2; }
globalThis.tag = A;
f();
const arr = [];
arr.push(1);
export { A };
";
        let module = parse(src);
        let analysis = analyze_chunk(&module, &AnalysisHints::default(), None, |_| None);
        assert!(!analysis.facts.is_empty(), "fixture must produce facts");

        // Per-statement round trip.
        for original in &analysis.facts {
            let report = StatementFactsReport::from_facts(original);
            let json = serde_json::to_string(&report).expect("serialize");
            let decoded: StatementFactsReport = serde_json::from_str(&json).expect("deserialize");
            let restored = decoded.to_facts();
            facts_equiv(original, &restored);
        }

        // Whole-analysis round trip.
        let envelope = ChunkFactsReport::from_analysis(&analysis);
        let json = serde_json::to_string(&envelope).expect("serialize envelope");
        let decoded: ChunkFactsReport = serde_json::from_str(&json).expect("deserialize envelope");
        let restored = decoded.to_analysis();
        assert_eq!(analysis.facts.len(), restored.facts.len());
        for (orig, restored) in analysis.facts.iter().zip(restored.facts.iter()) {
            facts_equiv(orig, restored);
        }
        assert_eq!(analysis.top_level_await, restored.top_level_await);
        assert_eq!(
            analysis.redundant_purity_hints,
            restored.redundant_purity_hints
        );
        assert_eq!(
            analysis.redundant_pure_member_hints,
            restored.redundant_pure_member_hints
        );
    }

    /// JSON shape sanity check: the envelope carries `schema_version`,
    /// `eager_reads` deserializes as a JSON array, and `EffectCell`
    /// variants are tagged.
    #[test]
    fn json_shape_is_reasonable() {
        let module = parse("const A = 1;\nglobalThis.tag = A;\nexport { A };\n");
        let analysis = analyze_chunk(&module, &AnalysisHints::default(), None, |_| None);
        let envelope = ChunkFactsReport::from_analysis(&analysis);
        let value: serde_json::Value = serde_json::to_value(&envelope).expect("to_value");

        assert_eq!(
            value["schema_version"],
            serde_json::json!(SCHEMA_VERSION),
            "schema_version present at top level",
        );
        let facts = value["facts"].as_array().expect("facts is array");
        assert_eq!(facts.len(), analysis.facts.len());

        // Every statement's eager_reads must be an array.
        for stmt in facts {
            assert!(
                stmt["eager_reads"].is_array(),
                "eager_reads must be a JSON array, got {stmt:?}",
            );
            assert!(
                stmt["effects"]["writes"].is_array(),
                "effects.writes must be a JSON array",
            );
            assert!(
                stmt["effects"]["reads"].is_array(),
                "effects.reads must be a JSON array",
            );
        }

        // One of the statements assigns `globalThis.tag = A`: its
        // effects.writes must contain a tagged `GlobalProp` cell.
        let mut saw_global_prop = false;
        for stmt in facts {
            for write in stmt["effects"]["writes"].as_array().unwrap() {
                if write["kind"] == "global_prop" && write["key"] == "tag" {
                    saw_global_prop = true;
                }
            }
        }
        assert!(
            saw_global_prop,
            "expected a `global_prop` write tagged `tag`",
        );
    }

    /// `IdReport::ctxt` must round-trip through `u32`.
    #[test]
    fn id_report_ctxt_round_trips_through_u32() {
        let module = parse("const A = 1;\n");
        let analysis = analyze_chunk(&module, &AnalysisHints::default(), None, |_| None);
        let facts = &analysis.facts[0];
        let original_id = facts.declared.iter().next().expect("one declared id");
        let report = IdReport::from_id(original_id);
        let json = serde_json::to_string(&report).expect("serialize id");
        let decoded: IdReport = serde_json::from_str(&json).expect("deserialize id");
        let restored = decoded.to_id();
        assert_eq!(*original_id, restored);
    }
}
