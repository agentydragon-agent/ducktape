"Linter aspects and test rules for the repository."

load("@aspect_rules_lint//lint:lint_test.bzl", "lint_test")
load("@aspect_rules_lint//lint:ruff.bzl", "lint_ruff_aspect")
load("@rules_mypy//mypy:mypy.bzl", "mypy")

# Ruff aspect for --config=lint builds
ruff = lint_ruff_aspect(
    binary = "@multitool//tools/ruff",
    configs = [
        Label("//:ruff.toml"),
    ],
)

# Mypy aspect for --config=typecheck builds
mypy_aspect = mypy()

# Test rule factories - use these in BUILD.bazel files:
#   load("//tools/lint:linters.bzl", "ruff_test")
#   ruff_test(name = "ruff", srcs = [":my_library"])
ruff_test = lint_test(aspect = ruff)
