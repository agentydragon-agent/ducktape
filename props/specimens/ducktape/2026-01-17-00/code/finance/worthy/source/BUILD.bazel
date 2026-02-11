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
