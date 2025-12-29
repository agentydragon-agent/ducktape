load("@buildifier_prebuilt//:rules.bzl", "buildifier")

# Exports for use in other BUILD files
exports_files([
    "requirements_bazel.txt",
])

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
