#load("@com_github_bazelbuild_buildtools//buildifier:def.bzl", "buildifier")
load(
    "@rules_rust//rust:defs.bzl",
    "rust_binary",
    #"rust_doc",
    "rust_library",
    "rust_test",
)

#buildifier(
#    name = "buildifier",
#)

rust_library(
    name = "source",
    srcs = ["source.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":asset",
    ],
)

rust_library(
    name = "converter",
    srcs = ["converter.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:async_trait",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":denomination",
        ":exchange_rate",
    ],
)

rust_library(
    name = "exchange_rate",
    srcs = ["exchange_rate.rs"],
    edition = "2021",
    visibility = ["//visibility:public"],
    deps = [
        ":denomination",
        "//remote:chrono",
        "//remote:chrono_tz",
        "//remote:rust_decimal",
    ],
)

rust_binary(
    name = "rust_main",
    srcs = ["main.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    deps = [
        ":asset",
        ":common_currency",
        ":config",
        ":converter",
        ":denomination",
        ":exchange_rate",
        ":flags",
        ":graph_output",
        ":json_output",
        ":solid_io",
        ":source",
        "//finance/worthy/converter:alphavantage_converter",
        "//finance/worthy/converter:coinbase_converter",
        "//finance/worthy/converter:currencylayer_converter",
        "//finance/worthy/converter:fixer_converter",
        "//finance/worthy/converter:swiss_fund_data_converter",
        "//finance/worthy/model:model_rs",
        "//finance/worthy/source:coinbase_source",
        "//finance/worthy/source:ftx_source",
        "//finance/worthy/source:ibflex_source",
        "//remote:chrono",
        "//remote:csv",
        "//remote:env_logger",
        "//remote:futures",
        "//remote:glob",
        "//remote:log",
        "//remote:reqwest",
        "//remote:rust_decimal",
        "//remote:rusty_money",
        "//remote:scraper",
        "//remote:serde_json",
        "//remote:serde_yaml",
        "//remote:shellexpand",
        "//remote:structopt",
        "//remote:term_table",
        "//remote:tokio",
        "//remote:xdg",
    ],
)

rust_library(
    name = "common_currency",
    srcs = ["common_currency.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":denomination",
        ":exchange_rate",
        "//remote:log",
        "//remote:petgraph",
        "//remote:rust_decimal",
    ],
)

rust_library(
    name =
        "graph_util",
    srcs = ["graph_util.rs"],
    edition = "2021",
    deps = [
        "//remote:sophia",
    ],
)

rust_library(
    name = "dpop_http_client",
    srcs = ["dpop_http_client.rs"],
    edition = "2021",
    deps = [
        "//remote:base64",
        "//remote:biscuit",
        "//remote:chrono",
        "//remote:jwt",
        "//remote:log",
        "//remote:oauth2",
        "//remote:openssl",
        "//remote:rand",
        "//remote:reqwest",
        "//remote:serde",
        "//remote:url",
    ],
)

rust_library(
    name = "solid_io",
    srcs = ["solid_io.rs"],
    edition = "2021",
    deps = [
        ":dpop_http_client",
        ":graph_output",
        ":graph_util",
        ":ns",
        "//remote:base64",
        "//remote:biscuit",
        "//remote:chrono",
        "//remote:env_logger",
        "//remote:jwt",
        "//remote:log",
        "//remote:oauth2",
        "//remote:openssl",
        "//remote:rand",
        "//remote:reqwest",
        "//remote:serde",
        "//remote:serde_json",
        "//remote:sophia",
        "//remote:sophia_term",
        "//remote:tokio",
        "//remote:url",
        "//remote:warp",
    ],
)

rust_test(
    name = "solid_io_test",
    srcs = ["solid_io_test.rs"],
    edition = "2021",
    deps = [
        ":solid_io",
        "//remote:env_logger",
        "//remote:sophia",
    ],
)

rust_test(
    name = "common_currency_test",
    srcs = ["common_currency_test.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    deps = [
        ":common_currency",
        ":denomination",
        ":exchange_rate",
        "//remote:env_logger",
        "//remote:log",
        "//remote:rust_decimal",
    ],
)

rust_library(
    name = "ibflex",
    srcs = ["ibflex.rs"],
    edition = "2021",
    visibility = ["//visibility:public"],
    deps = [
        "//remote:log",
        "//remote:reqwest",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_xml_rs",
        "//remote:tokio",
        "//remote:url",
    ],
)

rust_test(
    name = "ibflex_test",
    srcs = ["ibflex_test.rs"],
    edition = "2021",
    deps = [
        ":ibflex",
        "//remote:rust_decimal",
        "//remote:url",
    ],
)

#rust_doc(
#    name = "rust_doc",
#    dep = ":rust_main",
#)

rust_test(
    name = "rust_main_test",
    crate = ":rust_main",
)

rust_library(
    name = "denomination",
    srcs = ["denomination.rs"],
    edition = "2021",
    visibility = ["//visibility:public"],
    deps = [
        "//remote:serde",
    ],
)

rust_library(
    name = "asset",
    srcs = ["asset.rs"],
    edition = "2021",
    visibility = ["//visibility:public"],
    deps = [
        ":denomination",
        "//remote:rust_decimal",
        "//remote:serde",
    ],
)

rust_library(
    name = "flags",
    srcs = ["flags.rs"],
    edition = "2021",
    deps = [
        "//remote:serde",
        "//remote:structopt",
    ],
)

rust_library(
    name = "config",
    srcs = ["config.rs"],
    edition = "2021",
    deps = [
        ":asset",
        "//finance/worthy/converter:alphavantage_converter",
        "//finance/worthy/converter:coinbase_converter",
        "//finance/worthy/converter:currencylayer_converter",
        "//finance/worthy/converter:fixer_converter",
        "//finance/worthy/converter:swiss_fund_data_converter",
        "//finance/worthy/source:coinbase_source",
        "//finance/worthy/source:ftx_source",
        "//finance/worthy/source:ibflex_source",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_yaml",
    ],
)

rust_test(
    name = "flags_test",
    srcs = ["flags_test.rs"],
    edition = "2021",
    deps = [
        ":config",
        ":flags",
        "//remote:structopt",
    ],
)

rust_library(
    name = "graph_output",
    srcs = ["graph_output.rs"],
    edition = "2021",
    deps = [
        ":asset",
        ":denomination",
        ":exchange_rate",
        ":ns",
        "//remote:chrono",
        "//remote:sophia",
        "//remote:uuid",
    ],
)

rust_test(
    name = "graph_output_test",
    srcs = ["graph_output_test.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    deps = [
        ":asset",
        ":denomination",
        ":exchange_rate",
        ":graph_output",
        "//remote:chrono",
        "//remote:env_logger",
        "//remote:rust_decimal",
        "//remote:sophia",
    ],
)

rust_library(
    name = "json_output",
    srcs = ["json_output.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    deps = [
        "//remote:chrono",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_json",
    ],
)

rust_test(
    name = "json_output_test",
    srcs = ["json_output_test.rs"],
    edition = "2021",
    proc_macro_deps = [
        "//remote:rust_decimal_macros",
    ],
    deps = [
        ":json_output",
        "//remote:chrono",
        "//remote:rust_decimal",
        "//remote:serde",
        "//remote:serde_json",
    ],
)

rust_library(
    name = "ns",
    srcs = [
        "ns.rs",
    ],
    edition = "2021",
    deps = [
        "//remote:sophia",
    ],
)
