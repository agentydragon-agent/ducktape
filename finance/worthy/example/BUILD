load("@rules_rust//rust:defs.bzl", "rust_binary")

rust_binary(
    name = "swiss_fund_data",
    srcs = ["swiss_fund_data.rs"],
    edition = "2024",
    deps = [
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy/converter:swiss_fund_data_converter",
        "@crates//:env_logger",
        "@crates//:log",
        "@crates//:rust_decimal",
        "@crates//:structopt",
        "@crates//:tokio",
    ],
)
