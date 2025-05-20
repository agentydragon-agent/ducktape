load("@rules_python//python:defs.bzl", "py_library")
load("@rules_python//python:python.bzl", "py_binary")

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
    name = "ubs_credit_card_lib",
    srcs = ["ubs_credit_card_lib.py"],
    deps = [
        ":external_system",
    ],
)

py_library(
    name = "splitwise_lib",
    srcs = ["splitwise_lib.py"],
    deps = [
        "@pypi//absl_py",
        "@pypi//splitwise",
        # TODO: get rid of xdg requirement
        "@pypi//xdg",
        ":external_system",
    ],
)

py_binary(
    name = "reconcile",
    srcs = ["reconcile.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":splitwise_lib",
        ":ubs_credit_card_lib",
        ":ubs_lib",
        "//finance:gnucash_util",
        "@pypi//absl_py",
        "@pypi//xdg",
    ],
)
