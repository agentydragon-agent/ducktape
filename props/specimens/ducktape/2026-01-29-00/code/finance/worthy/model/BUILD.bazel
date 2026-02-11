load("@rules_rust//rust:defs.bzl", "rust_library")

rust_library(
    name = "model_rs",
    srcs = ["model.rs"],
    edition = "2024",
    proc_macro_deps = [
        "@crates//:rust_decimal_macros",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":differential",
        "@crates//:chrono",
        "@crates//:log",
        "@crates//:rust_decimal",
    ],
)

rust_library(
    name = "differential",
    srcs = ["differential.rs"],
    edition = "2024",
    proc_macro_deps = [
        "@crates//:rust_decimal_macros",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "@crates//:log",
        "@crates//:rust_decimal",
    ],
)
