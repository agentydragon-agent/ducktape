"""Common Python build macros for the ducktape repository."""

load("@rules_python//python:defs.bzl", "py_binary", "py_library", "py_test")

def ducktape_py_library(
        name,
        srcs = None,
        deps = None,
        data = None,
        imports = None,
        visibility = None,
        **kwargs):
    """Wrapper around py_library with common ducktape settings.

    Args:
        name: The name of the library target
        srcs: Python source files
        deps: Dependencies (both py_library and pip dependencies)
        data: Data files needed at runtime
        imports: Import paths to add to PYTHONPATH
        visibility: Target visibility
        **kwargs: Additional arguments passed to py_library
    """
    py_library(
        name = name,
        srcs = srcs if srcs != None else native.glob(["*.py"]),
        deps = deps or [],
        data = data or [],
        imports = imports or ["."],
        visibility = visibility,
        **kwargs
    )

def ducktape_py_binary(
        name,
        srcs = None,
        main = None,
        deps = None,
        data = None,
        imports = None,
        visibility = None,
        **kwargs):
    """Wrapper around py_binary with common ducktape settings.

    Args:
        name: The name of the binary target
        srcs: Python source files
        main: Main entry point file (defaults to name.py)
        deps: Dependencies (both py_library and pip dependencies)
        data: Data files needed at runtime
        imports: Import paths to add to PYTHONPATH
        visibility: Target visibility
        **kwargs: Additional arguments passed to py_binary
    """
    py_binary(
        name = name,
        srcs = srcs or [main or name + ".py"],
        main = main or name + ".py",
        deps = deps or [],
        data = data or [],
        imports = imports or ["."],
        visibility = visibility,
        **kwargs
    )

def ducktape_py_test(
        name,
        srcs = None,
        main = None,
        deps = None,
        data = None,
        imports = None,
        size = "small",
        python_version = "PY3",
        tags = None,
        **kwargs):
    """Wrapper around py_test with pytest support and common ducktape settings.

    This macro sets up a Python test target that uses pytest as the test runner.
    It automatically adds pytest and common test dependencies.

    Args:
        name: The name of the test target
        srcs: Test source files (defaults to test_*.py or *_test.py)
        main: Main entry point (if not using pytest runner)
        deps: Dependencies (both py_library and pip dependencies)
        data: Data files needed at runtime
        imports: Import paths to add to PYTHONPATH
        size: Test size (small/medium/large/enormous)
        python_version: Python version (PY3)
        tags: Additional tags for the test
        **kwargs: Additional arguments passed to py_test
    """
    test_tags = tags or []

    # Add pytest dependency
    test_deps = deps or []
    pytest_deps = [
        "@pypi//pytest:pkg",
        "@pypi//pytest_asyncio:pkg",
    ]
    test_deps = test_deps + pytest_deps

    # Default test sources pattern
    if srcs == None:
        srcs = native.glob([
            "test_*.py",
            "*_test.py",
        ])

    py_test(
        name = name,
        srcs = srcs,
        main = main or srcs[0] if srcs else name + ".py",
        deps = test_deps,
        data = data or [],
        imports = imports or ["."],
        size = size,
        python_version = python_version,
        tags = test_tags,
        # Use pytest as the test runner
        args = [
            "-v",
            "--tb=short",
        ] + kwargs.pop("args", []),
        **kwargs
    )

def ducktape_py_package(
        name,
        srcs = None,
        deps = None,
        data = None,
        tests = True,
        visibility = None):
    """Create a standard Python package with library and optional tests.

    This macro creates a py_library target and optionally discovers and creates
    test targets for test files in the package.

    Args:
        name: The base name for the package (typically the package directory name)
        srcs: Python source files (defaults to all *.py except test files)
        deps: Dependencies for the library
        data: Data files for the library
        tests: Whether to auto-discover and create test targets (default: True)
        visibility: Visibility for the library target
    """
    # Library sources exclude test files
    if srcs == None:
        srcs = native.glob(
            ["*.py"],
            exclude = [
                "test_*.py",
                "*_test.py",
                "conftest.py",
            ],
        )

    # Create the main library target
    ducktape_py_library(
        name = name,
        srcs = srcs,
        deps = deps,
        data = data,
        visibility = visibility,
    )

    # Auto-discover and create test targets
    if tests:
        test_files = native.glob([
            "test_*.py",
            "*_test.py",
        ])
        for test_file in test_files:
            # Create a test name from the file name
            test_name = test_file[:-3]  # Remove .py
            if test_name.startswith("test_"):
                test_name = test_name[5:]  # Remove test_ prefix
            elif test_name.endswith("_test"):
                test_name = test_name[:-5]  # Remove _test suffix

            ducktape_py_test(
                name = name + "_" + test_name + "_test",
                srcs = [test_file],
                deps = [
                    ":" + name,  # Depend on the library
                ] + (deps or []),
            )
