load("@my_deps//:requirements.bzl", "requirement")
load("@rules_python//python:python.bzl", "py_binary", "py_test")

py_library(
    name = "external_system",
    srcs = ["external_system.py"],
    deps = [
    ],
)

py_library(
    name = "ubs_lib",
    srcs = ["ubs_lib.py"],
    deps = [
        ":external_system",
    ],
)

py_library(
    name = "splitwise_lib",
    srcs = ["splitwise_lib.py"],
    deps = [
        requirement("absl-py"),
        requirement("splitwise"),
        # TODO: get rid of xdg requirement
        requirement("xdg"),
        ":external_system",
    ],
)

py_binary(
    name = "reconcile",
    srcs = ["reconcile.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":splitwise_lib",
        ":ubs_lib",
        requirement("absl-py"),
        requirement("xdg"),
        "//finance:gnucash_util",
    ],
)
