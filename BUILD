load("@my_deps//:requirements.bzl", "entry_point", "requirement")
load("@rules_python//python:defs.bzl", "py_binary", "py_test")
load("@rules_python//python/pip_install:requirements.bzl", "compile_pip_requirements")

py_test(
    name = "hello_test",
    srcs = ["hello_test.py"],
    deps = [
        requirement("absl-py"),
    ],
)

# Convenient way to update.
compile_pip_requirements(
    name = "requirements",
    extra_args = ["--allow-unsafe"],
    requirements_in = "requirements.in",
    requirements_txt = "requirements_lock.txt",
)
