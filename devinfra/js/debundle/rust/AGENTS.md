Inherits the repo-root instructions in `/home/agentydragon/code/ducktape-rust/AGENTS.md`.

# Rust Debundler Port Constraints

This port has non-negotiable constraints. Treat the legacy JavaScript debundler as the executable specification.

## Hard Constraints

- Exact parity with the JavaScript implementation is required.
- Parity means deep, end-to-end, structural parity across the full real pipeline: CLI behavior, stage behavior, intermediate semantics, emitted artifacts, snapshots, and browser-visible runtime behavior.
- No shallow fixes, fixture-shaped hacks, golden-specific workarounds, or “close enough” behavior are allowed.
- The Rust port must implement the full actual pipeline. Do not narrow the problem to only the currently failing fixture or one test surface unless the user explicitly scopes it down.

## AST Requirement

- JavaScript transformation work must use proper AST-based operations.
- Do not use raw text rewrites, string scanning, regex rewriting, ad hoc source patching, or other text-based mutation as a substitute for AST transformations.
- If the JavaScript implementation itself appears to rely on text-based hacks for a given behavior, stop and ask the user what to do before copying that approach into Rust.
- Absent explicit user direction otherwise, AST-based implementation is required.

## Working Rule

- If a proposed change improves a test result without improving true JS parity, do not make that change.
- If the easiest fix is not the deepest correct fix, do the deeper correct fix or stop and explain the blocker.
