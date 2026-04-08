"""Python rule wrappers that auto-inject repo-root imports."""

load("@rules_python//python:defs.bzl", _py_binary = "py_binary", _py_library = "py_library", _py_test = "py_test")

def repo_imports():
    """Compute imports path to the repository root from the current package.

    Returns:
        A single-element list with the relative path to the repo root.
    """
    pkg = native.package_name()
    if not pkg:
        return ["."]
    depth = pkg.count("/") + 1
    return ["/".join([".."] * depth)]

def py_library(imports = None, **kwargs):
    """py_library with auto repo-root imports."""
    if imports == None:
        imports = repo_imports()
    _py_library(imports = imports, **kwargs)

def py_binary(imports = None, **kwargs):
    """py_binary with auto repo-root imports."""
    if imports == None:
        imports = repo_imports()
    _py_binary(imports = imports, **kwargs)

def py_test(name, size = "small", requires_docker = False, tags = None, imports = None, **kwargs):
    """py_test with auto repo-root imports and sensible defaults.

    Args:
        name: Target name.
        size: Test size. Defaults to 'small' (60s timeout).
        requires_docker: Whether this test needs Docker. If True, adds the
            "requires_docker" tag for filtering.
        tags: Additional tags. Must not include "requires_docker" (use the parameter).
        imports: Python import paths. Defaults to repo root.
        **kwargs: Passed through to py_test.
    """
    if imports == None:
        imports = repo_imports()

    base_tags = tags or []
    if "requires_docker" in base_tags:
        fail("Use requires_docker parameter instead of 'requires_docker' tag in {}".format(name))
    if requires_docker:
        base_tags = base_tags + ["requires_docker"]

    _py_test(
        name = name,
        size = size,
        tags = base_tags,
        imports = imports,
        **kwargs
    )
