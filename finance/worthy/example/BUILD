load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_doc", "rust_library", "rust_test")

rust_binary(
    name = "swiss_fund_data",
    srcs = ["swiss_fund_data.rs"],
    edition = "2021",
    deps = [
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy/converter:swiss_fund_data_converter",
        "//remote:env_logger",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:structopt",
        "//remote:tokio",
    ],
)
