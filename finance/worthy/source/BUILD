load("@rules_rust//rust:defs.bzl", "rust_library")

rust_library(
    name = "ibflex_source",
    srcs = ["ibflex_source.rs"],
    edition = "2024",
    proc_macro_deps = [
        "@crates//:async-trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:ibflex",
        "//finance/worthy:source",
        "@crates//:rust_decimal",
        "@crates//:serde",
    ],
)

rust_library(
    name = "coinbase_source",
    srcs = ["coinbase_source.rs"],
    edition = "2024",
    proc_macro_deps = [
        "@crates//:async-trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:source",
        "@crates//:coinbase-rs",
        "@crates//:futures",
        "@crates//:log",
        "@crates//:rust_decimal",
        "@crates//:serde",
    ],
)

rust_library(
    name = "ftx_source",
    srcs = ["ftx_source.rs"],
    edition = "2024",
    proc_macro_deps = [
        "@crates//:async-trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:denomination",
        "//finance/worthy:source",
        "@crates//:ftx",
        "@crates//:log",
        "@crates//:rust_decimal",
        "@crates//:serde",
    ],
)
