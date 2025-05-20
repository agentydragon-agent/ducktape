load("@buildifier_prebuilt//:rules.bzl", "buildifier")
load("@rules_python//python/pip_install:requirements.bzl", "compile_pip_requirements")

# Convenient way to update.
compile_pip_requirements(
    name = "requirements",
    extra_args = ["--allow-unsafe"],
    requirements_in = "requirements.in",
    requirements_txt = "requirements_lock.txt",
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
