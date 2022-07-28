load("@rules_rust//rust:defs.bzl", "rust_library")

rust_library(
    name = "alphavantage_converter",
    srcs = ["alphavantage_converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy:exchange_rate",
        "//remote:alphavantage",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:serde",
    ],
)

rust_library(
    name = "currencylayer_converter",
    srcs = ["currencylayer_converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy:exchange_rate",
        "//remote:currency_layer",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:rusty_money",
        "//remote:serde",
    ],
)

rust_library(
    name = "coinbase_converter",
    srcs = ["coinbase_converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy:exchange_rate",
        "//remote:bigdecimal",
        "//remote:coinbase_rs",
        "//remote:futures",
        "//remote:log",
        "//remote:rust_decimal",
        "//remote:rusty_money",
        "//remote:serde",
    ],
)

rust_library(
    name = "swiss_fund_data_converter",
    srcs = ["swiss_fund_data_converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy:exchange_rate",
        "//remote:headless_chrome",
        "//remote:log",
        "//remote:regex",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_json",
    ],
)

rust_library(
    name = "fixer_converter",
    srcs = ["fixer_converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//finance/worthy:asset",
        "//finance/worthy:converter",
        "//finance/worthy:denomination",
        "//finance/worthy:exchange_rate",
        "//remote:log",
        "//remote:reqwest",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:url",
    ],
)
