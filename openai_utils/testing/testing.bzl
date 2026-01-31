"""Test macros for tests with mock and live OpenAI API variants."""

load("@rules_python//python:defs.bzl", "py_test")
load("//tools/testing:docker.bzl", "merge_docker_exec_properties")

# TODO: Consider removing Docker awareness from live_openai_*_py_test entirely.
# Options:
#   1. Have callers pass exec_properties=merge_docker_exec_properties() explicitly
#      (only mcp_infra/exec:test_exec_roundtrip currently needs this).
#   2. Compose with docker_py_test by having _maybe_docker_props callers use
#      docker_py_test directly — but Starlark macros can't wrap each other.
# Current approach: _maybe_docker_props delegates to shared merge_docker_exec_properties.
def _maybe_docker_props(tags, exec_properties):
    """Merge Docker exec properties if requires_docker is in tags."""
    if tags and "requires_docker" in tags:
        return merge_docker_exec_properties(exec_properties)
    return exec_properties

def live_openai_only_py_test(name, srcs, deps, live_env = None, tags = None, exec_properties = None, **kwargs):
    """py_test for files that contain only live OpenAI API tests.

    Generates a single target (no .mock/.live suffix) that runs with
    API key passthrough and the live_openai_api tag. If tags include
    "requires_docker", Firecracker exec properties are added automatically.

    Args:
        name: Target name.
        srcs: Python source files.
        deps: Dependencies.
        live_env: Env vars to inherit. Default: ["OPENAI_API_KEY", "OPENAI_MODEL"].
        tags: Base tags. "live_openai_api" is added automatically.
        exec_properties: Extra exec properties (merged with Docker defaults if applicable).
        **kwargs: Passed through to py_test (imports, data, etc).
    """
    live_env = live_env or ["OPENAI_API_KEY", "OPENAI_MODEL"]
    base_tags = tags or []
    live_tags = base_tags + ["live_openai_api", "no-remote-exec"]
    props = _maybe_docker_props(live_tags, exec_properties)

    if props:
        kwargs["exec_properties"] = props

    py_test(
        name = name,
        srcs = srcs,
        deps = deps,
        env_inherit = live_env,
        tags = live_tags,
        **kwargs
    )

def live_openai_py_test(name, srcs, deps, live_env = None, tags = None, exec_properties = None, **kwargs):
    """py_test that generates .mock and .live targets from one declaration.

    Tests in the source file use @pytest.mark.live_openai_api to mark live
    tests. The .mock target runs only non-live tests, and the .live target
    runs only live tests with API key passthrough. If tags include
    "requires_docker", Firecracker exec properties are added to both targets.

    Args:
        name: Base name. Generates {name}.mock and {name}.live.
        srcs: Python source files (shared by both targets).
        deps: Dependencies (shared by both targets).
        live_env: Env vars to inherit for .live target.
            Default: ["OPENAI_API_KEY", "OPENAI_MODEL"].
        tags: Base tags applied to both targets. The .live target
            additionally gets "live_openai_api".
        exec_properties: Extra exec properties (merged with Docker defaults if applicable).
        **kwargs: Passed through to both py_test calls (imports, data, etc).
    """
    live_env = live_env or ["OPENAI_API_KEY", "OPENAI_MODEL"]
    base_tags = tags or []
    live_tags = base_tags + ["live_openai_api", "no-remote-exec"]

    mock_props = _maybe_docker_props(base_tags, exec_properties)
    live_props = _maybe_docker_props(live_tags, exec_properties)

    # Derive main from srcs[0] so py_test doesn't infer it from the
    # suffixed target name (e.g. "test_foo.mock" → "test_foo.mock.py").
    main = srcs[0]

    # .mock — runs only non-live tests
    mock_kwargs = dict(kwargs)
    if mock_props:
        mock_kwargs["exec_properties"] = mock_props

    py_test(
        name = name + ".mock",
        srcs = srcs,
        deps = deps,
        main = main,
        args = ["-m", "'not live_openai_api'"],
        tags = base_tags,
        **mock_kwargs
    )

    # .live — runs only live tests, with API key passthrough
    live_kwargs = dict(kwargs)
    if live_props:
        live_kwargs["exec_properties"] = live_props

    py_test(
        name = name + ".live",
        srcs = srcs,
        deps = deps,
        main = main,
        args = ["-m", "live_openai_api"],
        env_inherit = live_env,
        tags = live_tags,
        **live_kwargs
    )
