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
//! 5. Validate realizability, derive peelability, and emit reports from that
//!    same graph model.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque};

use binding_targets::{
    TargetAccessRecorder, binding_names, record_assign_target, record_pat_write,
    record_update_target,
};
use petgraph::algo::{greedy_feedback_arc_set, tarjan_scc, toposort};
use petgraph::graph::{DiGraph, NodeIndex};
use petgraph::graphmap::DiGraphMap;
use petgraph::visit::EdgeRef;
use serde::{Deserialize, Serialize};
use swc_common::{Span, Spanned};
use swc_ecma_ast::*;
use swc_ecma_visit::{Visit, VisitWith};

include!("ids.rs");
include!("report_schema.rs");
include!("schedule.rs");
include!("facts.rs");
include!("purity.rs");
include!("graph.rs");
include!("reports.rs");
include!("peelability.rs");
include!("validation.rs");

#[cfg(test)]
include!("analysis_tests.rs");
