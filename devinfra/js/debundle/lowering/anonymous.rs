//! Shared materialization state for `anonymous_statements[]` claims and
//! diagnostics. Selector matching is handled by the global selector IR solver;
//! this module only carries resolved ordinals into the planner and renders
//! keep-going failures.

#[derive(Debug, Clone)]
pub(super) struct ResolvedAnonymousStatement {
    pub(super) ordinal: usize,
    pub(super) comment: Option<String>,
}

#[derive(Debug, Clone)]
pub(super) struct AnonymousStatementDiagnostic {
    pub(super) module_id: String,
    pub(super) selector: spec::AnonymousStatementSelector,
    pub(super) message: String,
    pub(super) root_isolation: Option<selector_diagnostics::SelectorRootIsolationReport>,
}

impl AnonymousStatementDiagnostic {
    pub(super) fn render(&self) -> String {
        let mut rendered = format!("module {}: {}", self.module_id, self.message);
        if let Some(root_isolation) = &self.root_isolation {
            rendered.push_str(" [root-isolation: ");
            rendered.push_str(&root_isolation.detail);
            rendered.push(']');
        }
        rendered
    }
}
