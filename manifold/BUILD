load(
    "@rules_rust//rust:defs.bzl",
    "rust_binary",
    "rust_library",
    #    "rust_test",
)

#rust_library(
#    name = "source",
#    srcs = ["source.rs"],
#    edition = "2021",
#    proc_macro_deps = [
#        "@crates//:async_trait",
#    ],
#    visibility = ["//visibility:public"],
#    deps = [
#        ":asset",
#    ],
#)

rust_library(
    name = "manifold_api",
    srcs = ["manifold_api.rs"],
    edition = "2021",
    deps = [
        "@crates//:log",
        "@crates//:reqwest",
        "@crates//:rust_decimal",
        "@crates//:serde",
        "@crates//:serde_json",
        "@crates//:serde_path_to_error",
        "@crates//:url",
    ],
)

rust_binary(
    name = "queue_main",
    srcs = ["queue.rs"],
    edition = "2021",
    deps = [
        ":manifold_api",
        "@crates//:tokio",
        "@crates//:serde",
        "@crates//:env_logger",
        "@crates//:log",
        "@crates//:serde_json",
        "@crates//:toml",
        #h"@crates//:serde_yaml",
    ],
)

rust_binary(
    name = "test_main",
    srcs = ["test.rs"],
    edition = "2021",
    deps = [
        "@crates//:serde",
        "@crates//:serde_json",
        "@crates//:toml",
        #h"@crates//:serde_yaml",
    ],
)
