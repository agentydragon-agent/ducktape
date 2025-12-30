load("@bazel_skylib//rules:native_binary.bzl", "native_test")
load("@buildifier_prebuilt//:rules.bzl", "buildifier")
load("@rules_python//python/uv:lock.bzl", "lock")
load("//.claude/claude-code-web:proxy_env.bzl", "PROXY_ENV")

# Exports for use in other BUILD files
exports_files([
    "requirements_bazel.txt",
    "ruff.toml",
])

# All pyproject.toml files that contribute to requirements_bazel.txt
# NOTE: homeassistant/iaqi excluded - its deps (pydantic 1.x, old pytest) conflict with repo
_PYPROJECT_SRCS = [
    "//adgn:pyproject.toml",
    "//agent_core:pyproject.toml",
    "//agent_pkg/host:pyproject.toml",
    "//agent_pkg/runtime:pyproject.toml",
    "//agent_server:pyproject.toml",
    "//claude/claude_hooks:pyproject.toml",
    "//claude/claude_optimizer:pyproject.toml",
    "//cli_util:pyproject.toml",
    "//difftree:pyproject.toml",
    "//editor_agent/host:pyproject.toml",
    "//editor_agent/runtime:pyproject.toml",
    "//ember:pyproject.toml",
    "//experimental/claude-history:pyproject.toml",
    "//finance:pyproject.toml",
    "//experimental/cotrl:pyproject.toml",
    "//experimental/dbus_fast_example:pyproject.toml",
    "//gatelet:pyproject.toml",
    "//git_commit_ai:pyproject.toml",
    "//gmail-archiver:pyproject.toml",
    "//gnome-terminal-profile-switcher:pyproject.toml",
    "//llm/ducktape_llm_common:pyproject.toml",
    "//llm/html:pyproject.toml",
    "//llm/mcp/habitify:pyproject.toml",
    "//mcp_infra:pyproject.toml",
    "//mcp_starter:pyproject.toml",
    "//mcp_utils:pyproject.toml",
    "//net_util:pyproject.toml",
    "//openai_utils:pyproject.toml",
    "//props/backend:pyproject.toml",
    "//props/core:pyproject.toml",
    "//py_detectors:pyproject.toml",
    "//:pyproject.toml",
    "//rspcache:pyproject.toml",
    "//sandboxed_jupyter:pyproject.toml",
    "//tana:pyproject.toml",
    "//wt:pyproject.toml",
]

# Generate requirements_bazel.txt from all pyproject.toml files
# Run: bazel run //:requirements.update
# Note: PROXY_ENV is loaded from //.claude/claude-code-web:proxy_env.bzl
# and is empty by default. On Claude Code web, the session-start hook
# overwrites it with actual proxy settings.
lock(
    name = "requirements",
    srcs = _PYPROJECT_SRCS,
    out = "requirements_bazel.txt",
    env = PROXY_ENV,
)

# Test that requirements_bazel.txt is up to date
# Run: bazel test //:requirements_test
native_test(
    name = "requirements_test",
    src = ":requirements.update",
    tags = [
        "no-cache",
        "requires-network",
    ],
)

platform(
    name = "linux_x64",
    constraint_values = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

# Format Bazel files
buildifier(
    name = "buildifier",
    lint_mode = "fix",
    mode = "fix",
)

# Check Bazel formatting
buildifier(
    name = "buildifier.check",
    lint_mode = "warn",
    mode = "diff",
)
