"""Test macros for tests with mock and live OpenAI API variants."""

load("@rules_python//python:defs.bzl", "py_library", "py_test")
load("//tools/testing:docker.bzl", "merge_docker_exec_properties")

_DEFAULT_LIVE_ENV = ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"]

def _maybe_docker_props(tags):
    """Return Docker exec properties if requires_docker is in tags."""
    if tags and "requires_docker" in tags:
        return merge_docker_exec_properties()
    return None

def _live_tags(base_tags):
    """Append live-only tags to base tags."""
    return base_tags + ["live_openai_api", "no-remote-exec"]

def _test_kwargs(base_kwargs, tags):
    """Build test kwargs with conditional exec_properties."""
    props = _maybe_docker_props(tags)
    if not props:
        return base_kwargs
    result = dict(base_kwargs)
    result["exec_properties"] = props
    return result

def live_openai_py_test(name, srcs, deps, imports = None, tags = None, **kwargs):
    """py_test that generates .mock and .live targets from one declaration.

    Tests in the source file use @pytest.mark.live_openai_api to mark live
    tests. A hidden py_library holds the shared source (compiled once),
    and both test targets use main_module = "pytest_bazel" as entry point.
    If tags include "requires_docker", Firecracker exec properties are added.

    Args:
        name: Base name. Generates {name}.mock, {name}.live, and {name}_lib.
        srcs: Python source files (owned by the hidden _lib target).
        deps: Dependencies (owned by the hidden _lib target).
        imports: Import path roots (passed to both _lib and test targets).
        tags: Base tags applied to both targets. The .live target
            additionally gets "live_openai_api".
        **kwargs: Passed through to test targets (data, env, timeout, size, etc).
    """
    base_tags = tags or []
    ltags = _live_tags(base_tags)

    # Hidden library owns the source — compiled once, no .pyc collision.
    lib_kwargs = {}
    if imports:
        lib_kwargs["imports"] = imports
    py_library(
        name = name + "_lib",
        srcs = srcs,
        deps = deps,
        testonly = True,
        **lib_kwargs
    )

    # Shared base for test kwargs (data, env, timeout, size, etc.)
    test_base = dict(kwargs)
    if imports:
        test_base["imports"] = imports

    # .mock — runs only non-live tests
    py_test(
        name = name + ".mock",
        main_module = "pytest_bazel",
        deps = [":" + name + "_lib", "@pypi//pytest_bazel"],
        args = ["-m", "'not live_openai_api'"],
        tags = base_tags,
        **_test_kwargs(test_base, base_tags)
    )

    # .live — runs only live tests, with API key passthrough
    py_test(
        name = name + ".live",
        main_module = "pytest_bazel",
        deps = [":" + name + "_lib", "@pypi//pytest_bazel"],
        args = ["-m", "live_openai_api"],
        env_inherit = _DEFAULT_LIVE_ENV,
        tags = ltags,
        **_test_kwargs(test_base, ltags)
    )
