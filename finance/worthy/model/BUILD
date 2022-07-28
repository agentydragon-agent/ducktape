load("@rules_rust//rust:defs.bzl", "rust_library")

rust_library(
    name = "model_rs",
    srcs = ["model.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":differential",
        "//remote:chrono",
        "//remote:log",
        "//remote:rust_decimal",
    ],
)

rust_library(
    name = "differential",
    srcs = ["differential.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//remote:log",
        "//remote:rust_decimal",
    ],
)
