//! Stage A composer for the per-chunk pipeline.
//!
//! See DESIGN.md §"Pipeline split (Stage A / Stage B)" and the
//! design proposal at `PIPELINE_SPLIT.md` for the broader plan.
//!
//! Stage A is the **spec-independent** half of the per-chunk
//! pipeline. Given a parsed chunk AST plus analysis hints + per-
//! chunk owner-graph options, it produces:
//!
//! - per-statement static facts (declared bindings, eager/lazy reads,
//!   side-effect summaries, purity classification, top-level-await
//!   detection);
//! - the owner graph derived from those facts;
//! - the structural atomic units (owner-level SCCs of `G_atomic`),
//!   which any valid factorization must keep co-located.
//!
//! Stage A is a pure function of `(module, hints, owner_graph_options)`
//! plus the spec-free `source_path` annotation and the line-index
//! callback for source-location resolution. It does not read the
//! spec, the partition, chunk renames, or the unassigned-mode
//! policy — those are Stage B inputs.
//!
//! v1 (this commit): Stage A is materialized only in memory, by
//! callers (today: `materialize_logical_chunk`) that call
//! [`compute_stage_one_analysis`] and pass its components to
//! Stage B. Follow-up tasks expose [`StageOneAnalysis`] as a serialized
//! sidecar artifact (per-concept JSON files under
//! `reports/tree/<chunk_id>/chunk_analysis/`) and add a Stage B
//! entry point that reads it back, so a Bazel rule can split into
//! two cacheable actions.
//!
//! Why a free function with no struct fanout: the existing pipeline
//! still owns the side-effect actions that sit between Stage A and
//! Stage B (redundant-hint warnings on stderr, top-level-await bail,
//! atomic-unit-rebind folding into the partition). Moving them all
//! through a freestanding `StageOneAnalysis` runner would require
//! threading more context than is paid for in v1. This composer
//! gives the boundary a single named call site without that wider
//! refactor.

pub mod sidecars;

use swc_common::Span;
use swc_ecma_ast::Module;

use crate::AnalysisHints;
use crate::atomic_units::{OwnerGraphAndUnits, compute_owner_graph_and_units_with};
use crate::facts::{ChunkFactAnalysis, analyze_chunk};
use crate::graph::OwnerGraphOptions;

/// Output of Stage A: the per-chunk analysis that does not depend on
/// the spec.
#[derive(Debug, Clone)]
pub struct StageOneAnalysis {
    /// Per-statement static facts plus chunk-wide flags (top-level
    /// await detection, redundant purity / pure-member hints).
    pub fact_analysis: ChunkFactAnalysis,
    /// Owner graph + structural atomic units derived from
    /// `fact_analysis.facts`. Carries no spec-dependent state; the
    /// atomic units here are the *structural* class (per DESIGN.md
    /// §"Two classes of atom") that any valid factorization must
    /// preserve.
    pub owner_graph_and_units: OwnerGraphAndUnits,
}

/// Run Stage A: analyze the chunk's facts, then derive the owner
/// graph + structural atomic units.
///
/// Equivalent to calling [`analyze_chunk`] followed by
/// [`compute_owner_graph_and_units_with`]; bundling the two into one
/// entry point fixes the Stage A boundary at a single named call
/// site that consumers (today the materializer; tomorrow a
/// standalone Bazel action) can reference.
pub fn compute_stage_one_analysis<F>(
    module: &Module,
    hints: &AnalysisHints,
    source_path: Option<&str>,
    line_range_for_span: F,
    owner_graph_options: OwnerGraphOptions,
) -> StageOneAnalysis
where
    F: FnMut(Span) -> Option<(usize, usize)>,
{
    let fact_analysis = analyze_chunk(module, hints, source_path, line_range_for_span);
    let owner_graph_and_units =
        compute_owner_graph_and_units_with(&fact_analysis.facts, owner_graph_options);
    StageOneAnalysis {
        fact_analysis,
        owner_graph_and_units,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use swc_common::{FileName, SourceMap, sync::Lrc};
    use swc_ecma_parser::{Parser, StringInput, Syntax, lexer::Lexer};

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

    /// Two-binding chunk: the composer must surface both the per-
    /// statement facts (one entry per top-level statement) and the
    /// derived owner graph (`compute_owner_graph_and_units_with`
    /// builds at least one node per declared binding plus an owner
    /// for each anonymous statement). The fixture exercises an
    /// at-init read (`const B = A + 1`) so the owner graph carries
    /// an `EagerUse` constraining edge — that edge collapses A's and
    /// B's owners into one structural atomic unit.
    #[test]
    fn composer_runs_facts_and_owner_graph_together() {
        let module = parse("const A = 1;\nconst B = A + 1;\nexport { A, B };\n");
        let stage_one = compute_stage_one_analysis(
            &module,
            &AnalysisHints::default(),
            None,
            |_| None,
            OwnerGraphOptions::default(),
        );

        // Three top-level items: two consts + one export.
        assert_eq!(stage_one.fact_analysis.facts.len(), 3);
        assert!(stage_one.fact_analysis.top_level_await.is_none());

        let owner_count = stage_one.owner_graph_and_units.owner_graph.nodes.len();
        assert!(
            owner_count >= 2,
            "owner graph must hold at least one node per declared \
             binding; got {owner_count}",
        );

        assert!(
            !stage_one.owner_graph_and_units.atomic_units.is_empty(),
            "atomic-units pass produced no structural units",
        );
    }
}
