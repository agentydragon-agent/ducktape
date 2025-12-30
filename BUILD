load("@buildifier_prebuilt//:rules.bzl", "buildifier")
load("@rules_python//python/uv:lock.bzl", "lock")

# Exports for use in other BUILD files
exports_files([
    "requirements_bazel.txt",
])

# Generate/update requirements_bazel.txt from pyproject.toml
# Run: bazel run //:requirements.update
lock(
    name = "requirements",
    srcs = ["pyproject.toml"],
    out = "requirements_bazel.txt",
    # Include dev dependencies for test packages
    args = [
        "--all-extras",
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
