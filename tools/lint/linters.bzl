"Linter aspects and test rules for the repository."

load("@aspect_rules_lint//lint:eslint.bzl", "lint_eslint_aspect")
load("@aspect_rules_lint//lint:lint_test.bzl", "lint_test")
load("@aspect_rules_lint//lint:ruff.bzl", "lint_ruff_aspect")
load("@rules_mypy//mypy:mypy.bzl", "mypy")

# Ruff aspect for --config=lint builds
# Uses ruff from the multitool lockfile bundled with aspect_rules_lint
ruff = lint_ruff_aspect(
    binary = "@multitool//tools/ruff",
    configs = [
        Label("//:ruff.toml"),
    ],
)

# Mypy aspect for --config=typecheck builds
# Uses root mypy.ini for configuration
#
# Type checking behavior:
# - Packages with py.typed (rich, structlog, aiohttp, aiodocker) are fully
#   type-checked - API misuse will be caught
# - Packages without py.typed (colorama, Pygments) need type stubs for full
#   checking. Pre-commit has these but Bazel needs a separate pip hub.
#   For now these packages get ignore_missing_imports treatment.
mypy_aspect = mypy(
    mypy_ini = Label("//:mypy.ini"),
)

# ESLint aspect for JS/TS linting
# Binary created in //tools/lint:eslint from props/frontend npm packages
eslint = lint_eslint_aspect(
    binary = Label("//tools/lint:eslint"),
    configs = [
        Label("//props/frontend:eslint.config.js"),
    ],
)

# Test rule factories - use these in BUILD.bazel files:
#   load("//tools/lint:linters.bzl", "ruff_test")
#   ruff_test(name = "ruff", srcs = [":my_library"])
ruff_test = lint_test(aspect = ruff)
eslint_test = lint_test(aspect = eslint)
