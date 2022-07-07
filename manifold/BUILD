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
#        "//remote:async_trait",
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
        "//remote:log",
        "//remote:reqwest",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_json",
        "//remote:serde_path_to_error",
        "//remote:url",
    ],
)

rust_binary(
    name = "queue_main",
    srcs = ["queue.rs"],
    edition = "2021",
    deps = [
        ":manifold_api",
        "//remote:tokio",
        "//remote:serde",
        "//remote:env_logger",
        "//remote:log",
        "//remote:serde_json",
        "//remote:toml",
        #h"//remote:serde_yaml",
    ],
)

rust_binary(
    name = "test_main",
    srcs = ["test.rs"],
    edition = "2021",
    deps = [
        "//remote:serde",
        "//remote:serde_json",
        "//remote:toml",
        #h"//remote:serde_yaml",
    ],
)
