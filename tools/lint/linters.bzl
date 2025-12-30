"Linter aspects for the repository."

load("@aspect_rules_lint//lint:ruff.bzl", "lint_ruff_aspect")
load("@rules_mypy//mypy:mypy.bzl", "mypy")

ruff = lint_ruff_aspect(
    binary = "@multitool//tools/ruff",
    configs = [
        Label("//:ruff.toml"),
    ],
)

mypy_aspect = mypy()
