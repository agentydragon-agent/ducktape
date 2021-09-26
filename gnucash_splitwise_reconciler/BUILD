load("@my_deps//:requirements.bzl", "requirement")
load("@rules_python//python:python.bzl", "py_binary", "py_test")

py_binary(
    name = "reconcile",
    srcs = ["reconcile.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("absl-py"),
        requirement("splitwise"),
        requirement("xdg"),
    ],
)
