"""Bazel rules for verifying dependency constraints."""

load("@rules_shell//shell:sh_test.bzl", "sh_test")

def assert_no_deps(name, target, forbidden_pattern, **kwargs):
    """Verify that target doesn't depend on packages matching forbidden_pattern.

    Creates a genquery + sh_test pair that fails if target has any transitive
    dependencies matching the forbidden pattern.

    Args:
        name: Test name (will also be used as prefix for genquery target)
        target: The target to check dependencies for (e.g., "//pkg:lib")
        forbidden_pattern: Regex pattern for forbidden deps (e.g., "@pypi//fastmcp|@pypi//mcp")
        **kwargs: Additional arguments passed to sh_test (e.g., tags)
    """
    query_name = name + "_query"

    native.genquery(
        name = query_name,
        expression = "filter('{}', deps({}))".format(forbidden_pattern, target),
        scope = [target],
    )
    sh_test(
        name = name,
        srcs = ["//tools/deps:assert_empty.sh"],
        data = [":" + query_name],
        args = ["$(location :{})".format(query_name)],
        **kwargs
    )
