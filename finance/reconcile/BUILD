load("@my_deps//:requirements.bzl", "requirement")
load("@rules_python//python:python.bzl", "py_binary", "py_test")

py_binary(
    name = "gnucash_splitwise",
    srcs = ["gnucash_splitwise.py"],
    visibility = ["//visibility:public"],
    # TODO: add gnucash
    deps = [
        requirement("absl-py"),
        requirement("splitwise"),
        requirement("xdg"),
        "//finance:gnucash_util",
    ],
)

py_binary(
    name = "gnucash_ubs_account_transactions",
    srcs = ["gnucash_ubs_account_transactions.py"],
    visibility = ["//visibility:public"],
    # TODO: add gnucash
    deps = [
        requirement("absl-py"),
        requirement("xdg"),
        "//finance:gnucash_util",
    ],
)
