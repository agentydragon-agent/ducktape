load("@rules_rust//rust:defs.bzl", "rust_library")

rust_library(
    name = "ibflex_source",
    srcs = ["ibflex_source.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:ibflex",
        "//finance/worthy:source",
        "//remote:rust_decimal",
        "//remote:serde",
    ],
)

rust_library(
    name = "coinbase_source",
    srcs = ["coinbase_source.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:source",
        "//remote:coinbase_rs",
        "//remote:futures",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:serde",
    ],
)

rust_library(
    name = "ftx_source",
    srcs = ["ftx_source.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:source",
        "//remote:ftx",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:serde",
    ],
)
