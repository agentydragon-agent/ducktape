# Debundle Code Quality Review (2026-05-09)

Highest-impact style/design/conciseness improvements identified across `devinfra/js/debundle/`.

## Pending

### 1. Deduplicate lazy-boundary visitor methods in `facts.rs`

`LazyReadCollector` (lines 482–562) and `BindingWriteCollector` (lines 575–697) have identical
`descend_lazy` methods and identical `visit_function`, `visit_arrow_expr`, `visit_method_prop`,
`visit_getter_prop`, `visit_setter_prop` implementations. The lazy/eager boundary logic could
live in a shared trait or base visitor that delegates to a callback, eliminating ~60 lines of
structural duplication.

### 2. Decouple `RewritableSpecifierDetector` from `RuntimeSourceRewriter` in `rewrite_specifiers.rs`

Both independently match the same five AST shapes (import decl, named export, export all,
dynamic import, new Worker) with the same guard conditions. The doc comment warns they must stay
in sync. A single declarative shape descriptor consumed by both visitors would eliminate the
lockstep coupling.
