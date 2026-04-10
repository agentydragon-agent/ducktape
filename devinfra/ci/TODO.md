# CI TODO

## Delete `compute-affected-targets` workflow

Once the GHA → BuildBuddy runners → RBE workflow is confirmed working, delete the
`compute-affected-targets` step from `ci.yml` and the supporting code (`ci_decide.py`,
`diff_utils.py`, `bazel-diff` download). The warm VM runners make cold Bazel cache
irrelevant, so target-level scoping provides no meaningful speedup. Currently `bazel-ci`
already runs `//...` unconditionally — the affected targets output is unused by the main
build job.
