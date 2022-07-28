"""
@generated
cargo-raze generated Bazel file.

DO NOT EDIT! Replaced on runs of cargo-raze
"""

load("@bazel_tools//tools/build_defs/repo:git.bzl", "new_git_repository")  # buildifier: disable=load
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")  # buildifier: disable=load
load("@bazel_tools//tools/build_defs/repo:utils.bzl", "maybe")  # buildifier: disable=load

def raze_fetch_remote_crates():
    """This function defines a collection of repos and should be called in a WORKSPACE file"""
    maybe(
        http_archive,
        name = "raze__addr2line__0_17_0",
        url = "https://crates.io/api/v1/crates/addr2line/0.17.0/download",
        type = "tar.gz",
        sha256 = "b9ecd88a8c8378ca913a680cd98f0f13ac67383d35993f86c90a70e3f137816b",
        strip_prefix = "addr2line-0.17.0",
        build_file = Label("//remote/remote:BUILD.addr2line-0.17.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__adler__1_0_2",
        url = "https://crates.io/api/v1/crates/adler/1.0.2/download",
        type = "tar.gz",
        sha256 = "f26201604c87b1e01bd3d98f8d5d9a8fcbb815e8cedb41ffccbeb4bf593a35fe",
        strip_prefix = "adler-1.0.2",
        build_file = Label("//remote/remote:BUILD.adler-1.0.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__aho_corasick__0_5_3",
        url = "https://crates.io/api/v1/crates/aho-corasick/0.5.3/download",
        type = "tar.gz",
        sha256 = "ca972c2ea5f742bfce5687b9aef75506a764f61d37f8f649047846a9686ddb66",
        strip_prefix = "aho-corasick-0.5.3",
        build_file = Label("//remote/remote:BUILD.aho-corasick-0.5.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__aho_corasick__0_6_10",
        url = "https://crates.io/api/v1/crates/aho-corasick/0.6.10/download",
        type = "tar.gz",
        sha256 = "81ce3d38065e618af2d7b77e10c5ad9a069859b4be3c2250f674af3840d9c8a5",
        strip_prefix = "aho-corasick-0.6.10",
        build_file = Label("//remote/remote:BUILD.aho-corasick-0.6.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__aho_corasick__0_7_18",
        url = "https://crates.io/api/v1/crates/aho-corasick/0.7.18/download",
        type = "tar.gz",
        sha256 = "1e37cfd5e7657ada45f742d6e99ca5788580b5c529dc78faf11ece6dc702656f",
        strip_prefix = "aho-corasick-0.7.18",
        build_file = Label("//remote/remote:BUILD.aho-corasick-0.7.18.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__alphavantage__0_7_0",
        url = "https://crates.io/api/v1/crates/alphavantage/0.7.0/download",
        type = "tar.gz",
        sha256 = "490b6310f1e97b41b8a33e23063d69db48f9534dea0db9322eaa6d4f06d4dc9c",
        strip_prefix = "alphavantage-0.7.0",
        build_file = Label("//remote/remote:BUILD.alphavantage-0.7.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ansi_term__0_12_1",
        url = "https://crates.io/api/v1/crates/ansi_term/0.12.1/download",
        type = "tar.gz",
        sha256 = "d52a9bb7ec0cf484c551830a7ce27bd20d67eac647e1befb56b0be4ee39a55d2",
        strip_prefix = "ansi_term-0.12.1",
        build_file = Label("//remote/remote:BUILD.ansi_term-0.12.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__arrayvec__0_7_2",
        url = "https://crates.io/api/v1/crates/arrayvec/0.7.2/download",
        type = "tar.gz",
        sha256 = "8da52d66c7071e2e3fa2a1e5c6d088fec47b593032b254f5e980de8ea54454d6",
        strip_prefix = "arrayvec-0.7.2",
        build_file = Label("//remote/remote:BUILD.arrayvec-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__async_stream__0_3_3",
        url = "https://crates.io/api/v1/crates/async-stream/0.3.3/download",
        type = "tar.gz",
        sha256 = "dad5c83079eae9969be7fadefe640a1c566901f05ff91ab221de4b6f68d9507e",
        strip_prefix = "async-stream-0.3.3",
        build_file = Label("//remote/remote:BUILD.async-stream-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__async_stream_impl__0_3_3",
        url = "https://crates.io/api/v1/crates/async-stream-impl/0.3.3/download",
        type = "tar.gz",
        sha256 = "10f203db73a71dfa2fb6dd22763990fa26f3d2625a6da2da900d23b87d26be27",
        strip_prefix = "async-stream-impl-0.3.3",
        build_file = Label("//remote/remote:BUILD.async-stream-impl-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__async_trait__0_1_56",
        url = "https://crates.io/api/v1/crates/async-trait/0.1.56/download",
        type = "tar.gz",
        sha256 = "96cf8829f67d2eab0b2dfa42c5d0ef737e0724e4a82b01b3e292456202b19716",
        strip_prefix = "async-trait-0.1.56",
        build_file = Label("//remote/remote:BUILD.async-trait-0.1.56.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__atty__0_2_14",
        url = "https://crates.io/api/v1/crates/atty/0.2.14/download",
        type = "tar.gz",
        sha256 = "d9b39be18770d11421cdb1b9947a45dd3f37e93092cbf377614828a319d5fee8",
        strip_prefix = "atty-0.2.14",
        build_file = Label("//remote/remote:BUILD.atty-0.2.14.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__autocfg__0_1_8",
        url = "https://crates.io/api/v1/crates/autocfg/0.1.8/download",
        type = "tar.gz",
        sha256 = "0dde43e75fd43e8a1bf86103336bc699aa8d17ad1be60c76c0bdfd4828e19b78",
        strip_prefix = "autocfg-0.1.8",
        build_file = Label("//remote/remote:BUILD.autocfg-0.1.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__autocfg__1_1_0",
        url = "https://crates.io/api/v1/crates/autocfg/1.1.0/download",
        type = "tar.gz",
        sha256 = "d468802bab17cbc0cc575e9b053f41e72aa36bfa6b7f55e3529ffa43161b97fa",
        strip_prefix = "autocfg-1.1.0",
        build_file = Label("//remote/remote:BUILD.autocfg-1.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__backtrace__0_3_66",
        url = "https://crates.io/api/v1/crates/backtrace/0.3.66/download",
        type = "tar.gz",
        sha256 = "cab84319d616cfb654d03394f38ab7e6f0919e181b1b57e1fd15e7fb4077d9a7",
        strip_prefix = "backtrace-0.3.66",
        build_file = Label("//remote/remote:BUILD.backtrace-0.3.66.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__base64__0_10_1",
        url = "https://crates.io/api/v1/crates/base64/0.10.1/download",
        type = "tar.gz",
        sha256 = "0b25d992356d2eb0ed82172f5248873db5560c4721f564b13cb5193bda5e668e",
        strip_prefix = "base64-0.10.1",
        build_file = Label("//remote/remote:BUILD.base64-0.10.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__base64__0_13_0",
        url = "https://crates.io/api/v1/crates/base64/0.13.0/download",
        type = "tar.gz",
        sha256 = "904dfeac50f3cdaba28fc6f57fdcddb75f49ed61346676a78c4ffe55877802fd",
        strip_prefix = "base64-0.13.0",
        build_file = Label("//remote/remote:BUILD.base64-0.13.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__base64__0_9_3",
        url = "https://crates.io/api/v1/crates/base64/0.9.3/download",
        type = "tar.gz",
        sha256 = "489d6c0ed21b11d038c31b6ceccca973e65d73ba3bd8ecb9a2babf5546164643",
        strip_prefix = "base64-0.9.3",
        build_file = Label("//remote/remote:BUILD.base64-0.9.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__bigdecimal__0_3_0",
        url = "https://crates.io/api/v1/crates/bigdecimal/0.3.0/download",
        type = "tar.gz",
        sha256 = "6aaf33151a6429fe9211d1b276eafdf70cdff28b071e76c0b0e1503221ea3744",
        strip_prefix = "bigdecimal-0.3.0",
        build_file = Label("//remote/remote:BUILD.bigdecimal-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__biscuit__0_5_0",
        url = "https://crates.io/api/v1/crates/biscuit/0.5.0/download",
        type = "tar.gz",
        sha256 = "0dee631cea28b00e115fd355a1adedc860b155096941dc01259969eabd434a37",
        strip_prefix = "biscuit-0.5.0",
        build_file = Label("//remote/remote:BUILD.biscuit-0.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__bitflags__1_3_2",
        url = "https://crates.io/api/v1/crates/bitflags/1.3.2/download",
        type = "tar.gz",
        sha256 = "bef38d45163c2f1dde094a7dfd33ccf595c92905c8f8f4fdc18d06fb1037718a",
        strip_prefix = "bitflags-1.3.2",
        build_file = Label("//remote/remote:BUILD.bitflags-1.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__block_buffer__0_10_2",
        url = "https://crates.io/api/v1/crates/block-buffer/0.10.2/download",
        type = "tar.gz",
        sha256 = "0bf7fe51849ea569fd452f37822f606a5cabb684dc918707a0193fd4664ff324",
        strip_prefix = "block-buffer-0.10.2",
        build_file = Label("//remote/remote:BUILD.block-buffer-0.10.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__block_buffer__0_7_3",
        url = "https://crates.io/api/v1/crates/block-buffer/0.7.3/download",
        type = "tar.gz",
        sha256 = "c0940dc441f31689269e10ac70eb1002a3a1d3ad1390e030043662eb7fe4688b",
        strip_prefix = "block-buffer-0.7.3",
        build_file = Label("//remote/remote:BUILD.block-buffer-0.7.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__block_buffer__0_9_0",
        url = "https://crates.io/api/v1/crates/block-buffer/0.9.0/download",
        type = "tar.gz",
        sha256 = "4152116fd6e9dadb291ae18fc1ec3575ed6d84c29642d97890f4b4a3417297e4",
        strip_prefix = "block-buffer-0.9.0",
        build_file = Label("//remote/remote:BUILD.block-buffer-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__block_padding__0_1_5",
        url = "https://crates.io/api/v1/crates/block-padding/0.1.5/download",
        type = "tar.gz",
        sha256 = "fa79dedbb091f449f1f39e53edf88d5dbe95f895dae6135a8d7b881fb5af73f5",
        strip_prefix = "block-padding-0.1.5",
        build_file = Label("//remote/remote:BUILD.block-padding-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__bstr__0_2_17",
        url = "https://crates.io/api/v1/crates/bstr/0.2.17/download",
        type = "tar.gz",
        sha256 = "ba3569f383e8f1598449f1a423e72e99569137b47740b1da11ef19af3d5c3223",
        strip_prefix = "bstr-0.2.17",
        build_file = Label("//remote/remote:BUILD.bstr-0.2.17.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__buf_redux__0_8_4",
        url = "https://crates.io/api/v1/crates/buf_redux/0.8.4/download",
        type = "tar.gz",
        sha256 = "b953a6887648bb07a535631f2bc00fbdb2a2216f135552cb3f534ed136b9c07f",
        strip_prefix = "buf_redux-0.8.4",
        build_file = Label("//remote/remote:BUILD.buf_redux-0.8.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__bumpalo__3_10_0",
        url = "https://crates.io/api/v1/crates/bumpalo/3.10.0/download",
        type = "tar.gz",
        sha256 = "37ccbd214614c6783386c1af30caf03192f17891059cecc394b4fb119e363de3",
        strip_prefix = "bumpalo-3.10.0",
        build_file = Label("//remote/remote:BUILD.bumpalo-3.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__byte_tools__0_3_1",
        url = "https://crates.io/api/v1/crates/byte-tools/0.3.1/download",
        type = "tar.gz",
        sha256 = "e3b5ca7a04898ad4bcd41c90c5285445ff5b791899bb1b0abdd2a2aa791211d7",
        strip_prefix = "byte-tools-0.3.1",
        build_file = Label("//remote/remote:BUILD.byte-tools-0.3.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__byteorder__1_4_3",
        url = "https://crates.io/api/v1/crates/byteorder/1.4.3/download",
        type = "tar.gz",
        sha256 = "14c189c53d098945499cdfa7ecc63567cf3886b3332b312a5b4585d8d3a6a610",
        strip_prefix = "byteorder-1.4.3",
        build_file = Label("//remote/remote:BUILD.byteorder-1.4.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__bytes__1_2_0",
        url = "https://crates.io/api/v1/crates/bytes/1.2.0/download",
        type = "tar.gz",
        sha256 = "f0b3de4a0c5e67e16066a0715723abd91edc2f9001d09c46e1dca929351e130e",
        strip_prefix = "bytes-1.2.0",
        build_file = Label("//remote/remote:BUILD.bytes-1.2.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cc__1_0_73",
        url = "https://crates.io/api/v1/crates/cc/1.0.73/download",
        type = "tar.gz",
        sha256 = "2fff2a6927b3bb87f9595d67196a70493f627687a71d87a0d692242c33f58c11",
        strip_prefix = "cc-1.0.73",
        build_file = Label("//remote/remote:BUILD.cc-1.0.73.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cfg_if__1_0_0",
        url = "https://crates.io/api/v1/crates/cfg-if/1.0.0/download",
        type = "tar.gz",
        sha256 = "baf1de4339761588bc0619e3cbc0120ee582ebb74b53b4efbf79117bd2da40fd",
        strip_prefix = "cfg-if-1.0.0",
        build_file = Label("//remote/remote:BUILD.cfg-if-1.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__chrono__0_4_19",
        url = "https://crates.io/api/v1/crates/chrono/0.4.19/download",
        type = "tar.gz",
        sha256 = "670ad68c9088c2a963aaa298cb369688cf3f9465ce5e2d4ca10e6e0098a1ce73",
        strip_prefix = "chrono-0.4.19",
        build_file = Label("//remote/remote:BUILD.chrono-0.4.19.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__chrono_tz__0_4_1",
        url = "https://crates.io/api/v1/crates/chrono-tz/0.4.1/download",
        type = "tar.gz",
        sha256 = "aa1878c18b5b01b9978d5f130fe366d434022004d12fb87c182e8459b427c4a3",
        strip_prefix = "chrono-tz-0.4.1",
        build_file = Label("//remote/remote:BUILD.chrono-tz-0.4.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__chrono_tz__0_6_3",
        url = "https://crates.io/api/v1/crates/chrono-tz/0.6.3/download",
        type = "tar.gz",
        sha256 = "29c39203181991a7dd4343b8005bd804e7a9a37afb8ac070e43771e8c820bbde",
        strip_prefix = "chrono-tz-0.6.3",
        build_file = Label("//remote/remote:BUILD.chrono-tz-0.6.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__chrono_tz_build__0_0_3",
        url = "https://crates.io/api/v1/crates/chrono-tz-build/0.0.3/download",
        type = "tar.gz",
        sha256 = "6f509c3a87b33437b05e2458750a0700e5bdd6956176773e6c7d6dd15a283a0c",
        strip_prefix = "chrono-tz-build-0.0.3",
        build_file = Label("//remote/remote:BUILD.chrono-tz-build-0.0.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__clap__2_34_0",
        url = "https://crates.io/api/v1/crates/clap/2.34.0/download",
        type = "tar.gz",
        sha256 = "a0610544180c38b88101fecf2dd634b174a62eef6946f84dfc6a7127512b381c",
        strip_prefix = "clap-2.34.0",
        build_file = Label("//remote/remote:BUILD.clap-2.34.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cloudabi__0_0_3",
        url = "https://crates.io/api/v1/crates/cloudabi/0.0.3/download",
        type = "tar.gz",
        sha256 = "ddfc5b9aa5d4507acaf872de71051dfd0e309860e88966e1051e462a077aac4f",
        strip_prefix = "cloudabi-0.0.3",
        build_file = Label("//remote/remote:BUILD.cloudabi-0.0.3.bazel"),
    )

    maybe(
        new_git_repository,
        name = "raze__coinbase_rs__0_3_0",
        remote = "https://github.com/agentydragon/coinbase-rs",
        commit = "01cabaa6fdd0fed87b44b38f218b1068f4914b39",
        build_file = Label("//remote/remote:BUILD.coinbase-rs-0.3.0.bazel"),
        init_submodules = True,
    )

    maybe(
        http_archive,
        name = "raze__convert_case__0_4_0",
        url = "https://crates.io/api/v1/crates/convert_case/0.4.0/download",
        type = "tar.gz",
        sha256 = "6245d59a3e82a7fc217c5828a6692dbc6dfb63a0c8c90495621f7b9d79704a0e",
        strip_prefix = "convert_case-0.4.0",
        build_file = Label("//remote/remote:BUILD.convert_case-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__core_foundation__0_9_3",
        url = "https://crates.io/api/v1/crates/core-foundation/0.9.3/download",
        type = "tar.gz",
        sha256 = "194a7a9e6de53fa55116934067c844d9d749312f75c6f6d0980e8c252f8c2146",
        strip_prefix = "core-foundation-0.9.3",
        build_file = Label("//remote/remote:BUILD.core-foundation-0.9.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__core_foundation_sys__0_8_3",
        url = "https://crates.io/api/v1/crates/core-foundation-sys/0.8.3/download",
        type = "tar.gz",
        sha256 = "5827cebf4670468b8772dd191856768aedcb1b0278a04f989f7766351917b9dc",
        strip_prefix = "core-foundation-sys-0.8.3",
        build_file = Label("//remote/remote:BUILD.core-foundation-sys-0.8.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cpufeatures__0_2_2",
        url = "https://crates.io/api/v1/crates/cpufeatures/0.2.2/download",
        type = "tar.gz",
        sha256 = "59a6001667ab124aebae2a495118e11d30984c3a653e99d86d58971708cf5e4b",
        strip_prefix = "cpufeatures-0.2.2",
        build_file = Label("//remote/remote:BUILD.cpufeatures-0.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__crc32fast__1_3_2",
        url = "https://crates.io/api/v1/crates/crc32fast/1.3.2/download",
        type = "tar.gz",
        sha256 = "b540bd8bc810d3885c6ea91e2018302f68baba2129ab3e88f32389ee9370880d",
        strip_prefix = "crc32fast-1.3.2",
        build_file = Label("//remote/remote:BUILD.crc32fast-1.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__crypto_common__0_1_6",
        url = "https://crates.io/api/v1/crates/crypto-common/0.1.6/download",
        type = "tar.gz",
        sha256 = "1bfb12502f3fc46cca1bb51ac28df9d618d813cdc3d2f25b9fe775a34af26bb3",
        strip_prefix = "crypto-common-0.1.6",
        build_file = Label("//remote/remote:BUILD.crypto-common-0.1.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__crypto_mac__0_7_0",
        url = "https://crates.io/api/v1/crates/crypto-mac/0.7.0/download",
        type = "tar.gz",
        sha256 = "4434400df11d95d556bac068ddfedd482915eb18fe8bea89bc80b6e4b1c179e5",
        strip_prefix = "crypto-mac-0.7.0",
        build_file = Label("//remote/remote:BUILD.crypto-mac-0.7.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cssparser__0_27_2",
        url = "https://crates.io/api/v1/crates/cssparser/0.27.2/download",
        type = "tar.gz",
        sha256 = "754b69d351cdc2d8ee09ae203db831e005560fc6030da058f86ad60c92a9cb0a",
        strip_prefix = "cssparser-0.27.2",
        build_file = Label("//remote/remote:BUILD.cssparser-0.27.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__cssparser_macros__0_6_0",
        url = "https://crates.io/api/v1/crates/cssparser-macros/0.6.0/download",
        type = "tar.gz",
        sha256 = "dfae75de57f2b2e85e8768c3ea840fd159c8f33e2b6522c7835b7abac81be16e",
        strip_prefix = "cssparser-macros-0.6.0",
        build_file = Label("//remote/remote:BUILD.cssparser-macros-0.6.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__csv__1_1_6",
        url = "https://crates.io/api/v1/crates/csv/1.1.6/download",
        type = "tar.gz",
        sha256 = "22813a6dc45b335f9bade10bf7271dc477e81113e89eb251a0bc2a8a81c536e1",
        strip_prefix = "csv-1.1.6",
        build_file = Label("//remote/remote:BUILD.csv-1.1.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__csv_core__0_1_10",
        url = "https://crates.io/api/v1/crates/csv-core/0.1.10/download",
        type = "tar.gz",
        sha256 = "2b2466559f260f48ad25fe6317b3c8dac77b5bdb5763ac7d9d6103530663bc90",
        strip_prefix = "csv-core-0.1.10",
        build_file = Label("//remote/remote:BUILD.csv-core-0.1.10.bazel"),
    )

    maybe(
        new_git_repository,
        name = "raze__currency_layer__0_1_2",
        remote = "https://github.com/agentydragon/currency-layer-rs",
        commit = "1f2f9af4dfb569808ca195f673452337b5e5d0be",
        build_file = Label("//remote/remote:BUILD.currency_layer-0.1.2.bazel"),
        init_submodules = True,
    )

    maybe(
        http_archive,
        name = "raze__darling__0_13_4",
        url = "https://crates.io/api/v1/crates/darling/0.13.4/download",
        type = "tar.gz",
        sha256 = "a01d95850c592940db9b8194bc39f4bc0e89dee5c4265e4b1807c34a9aba453c",
        strip_prefix = "darling-0.13.4",
        build_file = Label("//remote/remote:BUILD.darling-0.13.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__darling__0_9_0",
        url = "https://crates.io/api/v1/crates/darling/0.9.0/download",
        type = "tar.gz",
        sha256 = "fcfbcb0c5961907597a7d1148e3af036268f2b773886b8bb3eeb1e1281d3d3d6",
        strip_prefix = "darling-0.9.0",
        build_file = Label("//remote/remote:BUILD.darling-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__darling_core__0_13_4",
        url = "https://crates.io/api/v1/crates/darling_core/0.13.4/download",
        type = "tar.gz",
        sha256 = "859d65a907b6852c9361e3185c862aae7fafd2887876799fa55f5f99dc40d610",
        strip_prefix = "darling_core-0.13.4",
        build_file = Label("//remote/remote:BUILD.darling_core-0.13.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__darling_core__0_9_0",
        url = "https://crates.io/api/v1/crates/darling_core/0.9.0/download",
        type = "tar.gz",
        sha256 = "6afc018370c3bff3eb51f89256a6bdb18b4fdcda72d577982a14954a7a0b402c",
        strip_prefix = "darling_core-0.9.0",
        build_file = Label("//remote/remote:BUILD.darling_core-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__darling_macro__0_13_4",
        url = "https://crates.io/api/v1/crates/darling_macro/0.13.4/download",
        type = "tar.gz",
        sha256 = "9c972679f83bdf9c42bd905396b6c3588a843a17f0f16dfcfa3e2c5d57441835",
        strip_prefix = "darling_macro-0.13.4",
        build_file = Label("//remote/remote:BUILD.darling_macro-0.13.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__darling_macro__0_9_0",
        url = "https://crates.io/api/v1/crates/darling_macro/0.9.0/download",
        type = "tar.gz",
        sha256 = "c6d8dac1c6f1d29a41c4712b4400f878cb4fcc4c7628f298dd75038e024998d1",
        strip_prefix = "darling_macro-0.9.0",
        build_file = Label("//remote/remote:BUILD.darling_macro-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__data_encoding__2_3_2",
        url = "https://crates.io/api/v1/crates/data-encoding/2.3.2/download",
        type = "tar.gz",
        sha256 = "3ee2393c4a91429dffb4bedf19f4d6abf27d8a732c8ce4980305d782e5426d57",
        strip_prefix = "data-encoding-2.3.2",
        build_file = Label("//remote/remote:BUILD.data-encoding-2.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__derive_builder__0_7_2",
        url = "https://crates.io/api/v1/crates/derive_builder/0.7.2/download",
        type = "tar.gz",
        sha256 = "3ac53fa6a3cda160df823a9346442525dcaf1e171999a1cf23e67067e4fd64d4",
        strip_prefix = "derive_builder-0.7.2",
        build_file = Label("//remote/remote:BUILD.derive_builder-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__derive_builder_core__0_5_0",
        url = "https://crates.io/api/v1/crates/derive_builder_core/0.5.0/download",
        type = "tar.gz",
        sha256 = "0288a23da9333c246bb18c143426074a6ae96747995c5819d2947b64cd942b37",
        strip_prefix = "derive_builder_core-0.5.0",
        build_file = Label("//remote/remote:BUILD.derive_builder_core-0.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__derive_more__0_99_17",
        url = "https://crates.io/api/v1/crates/derive_more/0.99.17/download",
        type = "tar.gz",
        sha256 = "4fb810d30a7c1953f91334de7244731fc3f3c10d7fe163338a35b9f640960321",
        strip_prefix = "derive_more-0.99.17",
        build_file = Label("//remote/remote:BUILD.derive_more-0.99.17.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__digest__0_10_3",
        url = "https://crates.io/api/v1/crates/digest/0.10.3/download",
        type = "tar.gz",
        sha256 = "f2fb860ca6fafa5552fb6d0e816a69c8e49f0908bf524e30a90d97c85892d506",
        strip_prefix = "digest-0.10.3",
        build_file = Label("//remote/remote:BUILD.digest-0.10.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__digest__0_8_1",
        url = "https://crates.io/api/v1/crates/digest/0.8.1/download",
        type = "tar.gz",
        sha256 = "f3d0c8c8752312f9713efd397ff63acb9f85585afbf179282e720e7704954dd5",
        strip_prefix = "digest-0.8.1",
        build_file = Label("//remote/remote:BUILD.digest-0.8.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__digest__0_9_0",
        url = "https://crates.io/api/v1/crates/digest/0.9.0/download",
        type = "tar.gz",
        sha256 = "d3dd60d1080a57a05ab032377049e0591415d2b31afd7028356dbf3cc6dcb066",
        strip_prefix = "digest-0.9.0",
        build_file = Label("//remote/remote:BUILD.digest-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dirs__4_0_0",
        url = "https://crates.io/api/v1/crates/dirs/4.0.0/download",
        type = "tar.gz",
        sha256 = "ca3aa72a6f96ea37bbc5aa912f6788242832f75369bdfdadcb0e38423f100059",
        strip_prefix = "dirs-4.0.0",
        build_file = Label("//remote/remote:BUILD.dirs-4.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dirs_next__2_0_0",
        url = "https://crates.io/api/v1/crates/dirs-next/2.0.0/download",
        type = "tar.gz",
        sha256 = "b98cf8ebf19c3d1b223e151f99a4f9f0690dca41414773390fc824184ac833e1",
        strip_prefix = "dirs-next-2.0.0",
        build_file = Label("//remote/remote:BUILD.dirs-next-2.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dirs_sys__0_3_7",
        url = "https://crates.io/api/v1/crates/dirs-sys/0.3.7/download",
        type = "tar.gz",
        sha256 = "1b1d1d91c932ef41c0f2663aa8b0ca0342d444d842c06914aa0a7e352d0bada6",
        strip_prefix = "dirs-sys-0.3.7",
        build_file = Label("//remote/remote:BUILD.dirs-sys-0.3.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dirs_sys_next__0_1_2",
        url = "https://crates.io/api/v1/crates/dirs-sys-next/0.1.2/download",
        type = "tar.gz",
        sha256 = "4ebda144c4fe02d1f7ea1a7d9641b6fc6b580adcfa024ae48797ecdeb6825b4d",
        strip_prefix = "dirs-sys-next-0.1.2",
        build_file = Label("//remote/remote:BUILD.dirs-sys-next-0.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dotenv__0_15_0",
        url = "https://crates.io/api/v1/crates/dotenv/0.15.0/download",
        type = "tar.gz",
        sha256 = "77c90badedccf4105eca100756a0b1289e191f6fcbdadd3cee1d2f614f97da8f",
        strip_prefix = "dotenv-0.15.0",
        build_file = Label("//remote/remote:BUILD.dotenv-0.15.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dtoa__0_4_8",
        url = "https://crates.io/api/v1/crates/dtoa/0.4.8/download",
        type = "tar.gz",
        sha256 = "56899898ce76aaf4a0f24d914c97ea6ed976d42fec6ad33fcbb0a1103e07b2b0",
        strip_prefix = "dtoa-0.4.8",
        build_file = Label("//remote/remote:BUILD.dtoa-0.4.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__dtoa_short__0_3_3",
        url = "https://crates.io/api/v1/crates/dtoa-short/0.3.3/download",
        type = "tar.gz",
        sha256 = "bde03329ae10e79ede66c9ce4dc930aa8599043b0743008548680f25b91502d6",
        strip_prefix = "dtoa-short-0.3.3",
        build_file = Label("//remote/remote:BUILD.dtoa-short-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ego_tree__0_6_2",
        url = "https://crates.io/api/v1/crates/ego-tree/0.6.2/download",
        type = "tar.gz",
        sha256 = "3a68a4904193147e0a8dec3314640e6db742afd5f6e634f428a6af230d9b3591",
        strip_prefix = "ego-tree-0.6.2",
        build_file = Label("//remote/remote:BUILD.ego-tree-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__encoding_rs__0_8_31",
        url = "https://crates.io/api/v1/crates/encoding_rs/0.8.31/download",
        type = "tar.gz",
        sha256 = "9852635589dc9f9ea1b6fe9f05b50ef208c85c834a562f0c6abb1c475736ec2b",
        strip_prefix = "encoding_rs-0.8.31",
        build_file = Label("//remote/remote:BUILD.encoding_rs-0.8.31.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__env_logger__0_6_2",
        url = "https://crates.io/api/v1/crates/env_logger/0.6.2/download",
        type = "tar.gz",
        sha256 = "aafcde04e90a5226a6443b7aabdb016ba2f8307c847d524724bd9b346dd1a2d3",
        strip_prefix = "env_logger-0.6.2",
        build_file = Label("//remote/remote:BUILD.env_logger-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__env_logger__0_9_0",
        url = "https://crates.io/api/v1/crates/env_logger/0.9.0/download",
        type = "tar.gz",
        sha256 = "0b2cf0344971ee6c64c31be0d530793fba457d322dfec2810c453d0ef228f9c3",
        strip_prefix = "env_logger-0.9.0",
        build_file = Label("//remote/remote:BUILD.env_logger-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__failure__0_1_8",
        url = "https://crates.io/api/v1/crates/failure/0.1.8/download",
        type = "tar.gz",
        sha256 = "d32e9bd16cc02eae7db7ef620b392808b89f6a5e16bb3497d159c6b92a0f4f86",
        strip_prefix = "failure-0.1.8",
        build_file = Label("//remote/remote:BUILD.failure-0.1.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__failure_derive__0_1_8",
        url = "https://crates.io/api/v1/crates/failure_derive/0.1.8/download",
        type = "tar.gz",
        sha256 = "aa4da3c766cd7a0db8242e326e9e4e081edd567072893ed320008189715366a4",
        strip_prefix = "failure_derive-0.1.8",
        build_file = Label("//remote/remote:BUILD.failure_derive-0.1.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fake_simd__0_1_2",
        url = "https://crates.io/api/v1/crates/fake-simd/0.1.2/download",
        type = "tar.gz",
        sha256 = "e88a8acf291dafb59c2d96e8f59828f3838bb1a70398823ade51a84de6a6deed",
        strip_prefix = "fake-simd-0.1.2",
        build_file = Label("//remote/remote:BUILD.fake-simd-0.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fastrand__1_8_0",
        url = "https://crates.io/api/v1/crates/fastrand/1.8.0/download",
        type = "tar.gz",
        sha256 = "a7a407cfaa3385c4ae6b23e84623d48c2798d06e3e6a1878f7f59f17b3f86499",
        strip_prefix = "fastrand-1.8.0",
        build_file = Label("//remote/remote:BUILD.fastrand-1.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fixedbitset__0_4_2",
        url = "https://crates.io/api/v1/crates/fixedbitset/0.4.2/download",
        type = "tar.gz",
        sha256 = "0ce7134b9999ecaf8bcd65542e436736ef32ddca1b3e06094cb6ec5755203b80",
        strip_prefix = "fixedbitset-0.4.2",
        build_file = Label("//remote/remote:BUILD.fixedbitset-0.4.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fnv__1_0_7",
        url = "https://crates.io/api/v1/crates/fnv/1.0.7/download",
        type = "tar.gz",
        sha256 = "3f9eec918d3f24069decb9af1554cad7c880e2da24a9afd88aca000531ab82c1",
        strip_prefix = "fnv-1.0.7",
        build_file = Label("//remote/remote:BUILD.fnv-1.0.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__foreign_types__0_3_2",
        url = "https://crates.io/api/v1/crates/foreign-types/0.3.2/download",
        type = "tar.gz",
        sha256 = "f6f339eb8adc052cd2ca78910fda869aefa38d22d5cb648e6485e4d3fc06f3b1",
        strip_prefix = "foreign-types-0.3.2",
        build_file = Label("//remote/remote:BUILD.foreign-types-0.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__foreign_types_shared__0_1_1",
        url = "https://crates.io/api/v1/crates/foreign-types-shared/0.1.1/download",
        type = "tar.gz",
        sha256 = "00b0228411908ca8685dba7fc2cdd70ec9990a6e753e89b6ac91a84c40fbaf4b",
        strip_prefix = "foreign-types-shared-0.1.1",
        build_file = Label("//remote/remote:BUILD.foreign-types-shared-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__form_urlencoded__1_0_1",
        url = "https://crates.io/api/v1/crates/form_urlencoded/1.0.1/download",
        type = "tar.gz",
        sha256 = "5fc25a87fa4fd2094bffb06925852034d90a17f0d1e05197d4956d3555752191",
        strip_prefix = "form_urlencoded-1.0.1",
        build_file = Label("//remote/remote:BUILD.form_urlencoded-1.0.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ftx__0_5_0",
        url = "https://crates.io/api/v1/crates/ftx/0.5.0/download",
        type = "tar.gz",
        sha256 = "665160a6b6063a4bbc6c1e5ed4697a2da93133f49589dcca0270c8e6844286d2",
        strip_prefix = "ftx-0.5.0",
        build_file = Label("//remote/remote:BUILD.ftx-0.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fuchsia_cprng__0_1_1",
        url = "https://crates.io/api/v1/crates/fuchsia-cprng/0.1.1/download",
        type = "tar.gz",
        sha256 = "a06f77d526c1a601b7c4cdd98f54b5eaabffc14d5f2f0296febdc7f357c6d3ba",
        strip_prefix = "fuchsia-cprng-0.1.1",
        build_file = Label("//remote/remote:BUILD.fuchsia-cprng-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futf__0_1_5",
        url = "https://crates.io/api/v1/crates/futf/0.1.5/download",
        type = "tar.gz",
        sha256 = "df420e2e84819663797d1ec6544b13c5be84629e7bb00dc960d6917db2987843",
        strip_prefix = "futf-0.1.5",
        build_file = Label("//remote/remote:BUILD.futf-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures__0_3_21",
        url = "https://crates.io/api/v1/crates/futures/0.3.21/download",
        type = "tar.gz",
        sha256 = "f73fe65f54d1e12b726f517d3e2135ca3125a437b6d998caf1962961f7172d9e",
        strip_prefix = "futures-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_channel__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-channel/0.3.21/download",
        type = "tar.gz",
        sha256 = "c3083ce4b914124575708913bca19bfe887522d6e2e6d0952943f5eac4a74010",
        strip_prefix = "futures-channel-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-channel-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_core__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-core/0.3.21/download",
        type = "tar.gz",
        sha256 = "0c09fd04b7e4073ac7156a9539b57a484a8ea920f79c7c675d05d289ab6110d3",
        strip_prefix = "futures-core-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-core-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_executor__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-executor/0.3.21/download",
        type = "tar.gz",
        sha256 = "9420b90cfa29e327d0429f19be13e7ddb68fa1cccb09d65e5706b8c7a749b8a6",
        strip_prefix = "futures-executor-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-executor-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_io__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-io/0.3.21/download",
        type = "tar.gz",
        sha256 = "fc4045962a5a5e935ee2fdedaa4e08284547402885ab326734432bed5d12966b",
        strip_prefix = "futures-io-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-io-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_macro__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-macro/0.3.21/download",
        type = "tar.gz",
        sha256 = "33c1e13800337f4d4d7a316bf45a567dbcb6ffe087f16424852d97e97a91f512",
        strip_prefix = "futures-macro-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-macro-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_sink__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-sink/0.3.21/download",
        type = "tar.gz",
        sha256 = "21163e139fa306126e6eedaf49ecdb4588f939600f0b1e770f4205ee4b7fa868",
        strip_prefix = "futures-sink-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-sink-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_task__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-task/0.3.21/download",
        type = "tar.gz",
        sha256 = "57c66a976bf5909d801bbef33416c41372779507e7a6b3a5e25e4749c58f776a",
        strip_prefix = "futures-task-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-task-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__futures_util__0_3_21",
        url = "https://crates.io/api/v1/crates/futures-util/0.3.21/download",
        type = "tar.gz",
        sha256 = "d8b7abd5d659d9b90c8cba917f6ec750a74e2dc23902ef9cd4cc8c8b22e6036a",
        strip_prefix = "futures-util-0.3.21",
        build_file = Label("//remote/remote:BUILD.futures-util-0.3.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__fxhash__0_2_1",
        url = "https://crates.io/api/v1/crates/fxhash/0.2.1/download",
        type = "tar.gz",
        sha256 = "c31b6d751ae2c7f11320402d34e41349dd1016f8d5d45e48c4312bc8625af50c",
        strip_prefix = "fxhash-0.2.1",
        build_file = Label("//remote/remote:BUILD.fxhash-0.2.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__generic_array__0_12_4",
        url = "https://crates.io/api/v1/crates/generic-array/0.12.4/download",
        type = "tar.gz",
        sha256 = "ffdf9f34f1447443d37393cc6c2b8313aebddcd96906caf34e54c68d8e57d7bd",
        strip_prefix = "generic-array-0.12.4",
        build_file = Label("//remote/remote:BUILD.generic-array-0.12.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__generic_array__0_14_5",
        url = "https://crates.io/api/v1/crates/generic-array/0.14.5/download",
        type = "tar.gz",
        sha256 = "fd48d33ec7f05fbfa152300fdad764757cbded343c1aa1cff2fbaf4134851803",
        strip_prefix = "generic-array-0.14.5",
        build_file = Label("//remote/remote:BUILD.generic-array-0.14.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__getopts__0_2_21",
        url = "https://crates.io/api/v1/crates/getopts/0.2.21/download",
        type = "tar.gz",
        sha256 = "14dbbfd5c71d70241ecf9e6f13737f7b5ce823821063188d7e46c41d371eebd5",
        strip_prefix = "getopts-0.2.21",
        build_file = Label("//remote/remote:BUILD.getopts-0.2.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__getrandom__0_1_16",
        url = "https://crates.io/api/v1/crates/getrandom/0.1.16/download",
        type = "tar.gz",
        sha256 = "8fc3cb4d91f53b50155bdcfd23f6a4c39ae1969c2ae85982b135750cccaf5fce",
        strip_prefix = "getrandom-0.1.16",
        build_file = Label("//remote/remote:BUILD.getrandom-0.1.16.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__getrandom__0_2_7",
        url = "https://crates.io/api/v1/crates/getrandom/0.2.7/download",
        type = "tar.gz",
        sha256 = "4eb1a864a501629691edf6c15a593b7a51eebaa1e8468e9ddc623de7c9b58ec6",
        strip_prefix = "getrandom-0.2.7",
        build_file = Label("//remote/remote:BUILD.getrandom-0.2.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__gimli__0_26_2",
        url = "https://crates.io/api/v1/crates/gimli/0.26.2/download",
        type = "tar.gz",
        sha256 = "22030e2c5a68ec659fde1e949a745124b48e6fa8b045b7ed5bd1fe4ccc5c4e5d",
        strip_prefix = "gimli-0.26.2",
        build_file = Label("//remote/remote:BUILD.gimli-0.26.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__glob__0_3_0",
        url = "https://crates.io/api/v1/crates/glob/0.3.0/download",
        type = "tar.gz",
        sha256 = "9b919933a397b79c37e33b77bb2aa3dc8eb6e165ad809e58ff75bc7db2e34574",
        strip_prefix = "glob-0.3.0",
        build_file = Label("//remote/remote:BUILD.glob-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__h2__0_3_13",
        url = "https://crates.io/api/v1/crates/h2/0.3.13/download",
        type = "tar.gz",
        sha256 = "37a82c6d637fc9515a4694bbf1cb2457b79d81ce52b3108bdeea58b07dd34a57",
        strip_prefix = "h2-0.3.13",
        build_file = Label("//remote/remote:BUILD.h2-0.3.13.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hashbrown__0_12_3",
        url = "https://crates.io/api/v1/crates/hashbrown/0.12.3/download",
        type = "tar.gz",
        sha256 = "8a9ee70c43aaf417c914396645a0fa852624801b24ebb7ae78fe8272889ac888",
        strip_prefix = "hashbrown-0.12.3",
        build_file = Label("//remote/remote:BUILD.hashbrown-0.12.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__headers__0_3_7",
        url = "https://crates.io/api/v1/crates/headers/0.3.7/download",
        type = "tar.gz",
        sha256 = "4cff78e5788be1e0ab65b04d306b2ed5092c815ec97ec70f4ebd5aee158aa55d",
        strip_prefix = "headers-0.3.7",
        build_file = Label("//remote/remote:BUILD.headers-0.3.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__headers_core__0_2_0",
        url = "https://crates.io/api/v1/crates/headers-core/0.2.0/download",
        type = "tar.gz",
        sha256 = "e7f66481bfee273957b1f20485a4ff3362987f85b2c236580d81b4eb7a326429",
        strip_prefix = "headers-core-0.2.0",
        build_file = Label("//remote/remote:BUILD.headers-core-0.2.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__headless_chrome__0_9_0",
        url = "https://crates.io/api/v1/crates/headless_chrome/0.9.0/download",
        type = "tar.gz",
        sha256 = "b972f505b0adbacd697b3d78c94fbaf9c02d569ca11d416816956851f3a83017",
        strip_prefix = "headless_chrome-0.9.0",
        build_file = Label("//remote/remote:BUILD.headless_chrome-0.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__heck__0_3_3",
        url = "https://crates.io/api/v1/crates/heck/0.3.3/download",
        type = "tar.gz",
        sha256 = "6d621efb26863f0e9924c6ac577e8275e5e6b77455db64ffa6c65c904e9e132c",
        strip_prefix = "heck-0.3.3",
        build_file = Label("//remote/remote:BUILD.heck-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hermit_abi__0_1_19",
        url = "https://crates.io/api/v1/crates/hermit-abi/0.1.19/download",
        type = "tar.gz",
        sha256 = "62b467343b94ba476dcb2500d242dadbb39557df889310ac77c5d99100aaac33",
        strip_prefix = "hermit-abi-0.1.19",
        build_file = Label("//remote/remote:BUILD.hermit-abi-0.1.19.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hex__0_4_3",
        url = "https://crates.io/api/v1/crates/hex/0.4.3/download",
        type = "tar.gz",
        sha256 = "7f24254aa9a54b5c858eaee2f5bccdb46aaf0e486a595ed5fd8f86ba55232a70",
        strip_prefix = "hex-0.4.3",
        build_file = Label("//remote/remote:BUILD.hex-0.4.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hmac__0_12_1",
        url = "https://crates.io/api/v1/crates/hmac/0.12.1/download",
        type = "tar.gz",
        sha256 = "6c49c37c09c17a53d937dfbb742eb3a961d65a994e6bcdcf37e7399d0cc8ab5e",
        strip_prefix = "hmac-0.12.1",
        build_file = Label("//remote/remote:BUILD.hmac-0.12.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hmac__0_7_1",
        url = "https://crates.io/api/v1/crates/hmac/0.7.1/download",
        type = "tar.gz",
        sha256 = "5dcb5e64cda4c23119ab41ba960d1e170a774c8e4b9d9e6a9bc18aabf5e59695",
        strip_prefix = "hmac-0.7.1",
        build_file = Label("//remote/remote:BUILD.hmac-0.7.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hmac_sha256__0_1_7",
        url = "https://crates.io/api/v1/crates/hmac-sha256/0.1.7/download",
        type = "tar.gz",
        sha256 = "bcdc571e566521512579aab40bf807c5066e1765fb36857f16ed7595c13567c6",
        strip_prefix = "hmac-sha256-0.1.7",
        build_file = Label("//remote/remote:BUILD.hmac-sha256-0.1.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__html5ever__0_26_0",
        url = "https://crates.io/api/v1/crates/html5ever/0.26.0/download",
        type = "tar.gz",
        sha256 = "bea68cab48b8459f17cf1c944c67ddc572d272d9f2b274140f223ecb1da4a3b7",
        strip_prefix = "html5ever-0.26.0",
        build_file = Label("//remote/remote:BUILD.html5ever-0.26.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__http__0_2_8",
        url = "https://crates.io/api/v1/crates/http/0.2.8/download",
        type = "tar.gz",
        sha256 = "75f43d41e26995c17e71ee126451dd3941010b0514a81a9d11f3b341debc2399",
        strip_prefix = "http-0.2.8",
        build_file = Label("//remote/remote:BUILD.http-0.2.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__http_body__0_4_5",
        url = "https://crates.io/api/v1/crates/http-body/0.4.5/download",
        type = "tar.gz",
        sha256 = "d5f38f16d184e36f2408a55281cd658ecbd3ca05cce6d6510a176eca393e26d1",
        strip_prefix = "http-body-0.4.5",
        build_file = Label("//remote/remote:BUILD.http-body-0.4.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__httparse__1_7_1",
        url = "https://crates.io/api/v1/crates/httparse/1.7.1/download",
        type = "tar.gz",
        sha256 = "496ce29bb5a52785b44e0f7ca2847ae0bb839c9bd28f69acac9b99d461c0c04c",
        strip_prefix = "httparse-1.7.1",
        build_file = Label("//remote/remote:BUILD.httparse-1.7.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__httpdate__1_0_2",
        url = "https://crates.io/api/v1/crates/httpdate/1.0.2/download",
        type = "tar.gz",
        sha256 = "c4a1e36c821dbe04574f602848a19f742f4fb3c98d40449f11bcad18d6b17421",
        strip_prefix = "httpdate-1.0.2",
        build_file = Label("//remote/remote:BUILD.httpdate-1.0.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__humantime__1_3_0",
        url = "https://crates.io/api/v1/crates/humantime/1.3.0/download",
        type = "tar.gz",
        sha256 = "df004cfca50ef23c36850aaaa59ad52cc70d0e90243c3c7737a4dd32dc7a3c4f",
        strip_prefix = "humantime-1.3.0",
        build_file = Label("//remote/remote:BUILD.humantime-1.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__humantime__2_1_0",
        url = "https://crates.io/api/v1/crates/humantime/2.1.0/download",
        type = "tar.gz",
        sha256 = "9a3a5bfb195931eeb336b2a7b4d761daec841b97f947d34394601737a7bba5e4",
        strip_prefix = "humantime-2.1.0",
        build_file = Label("//remote/remote:BUILD.humantime-2.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hyper__0_10_16",
        url = "https://crates.io/api/v1/crates/hyper/0.10.16/download",
        type = "tar.gz",
        sha256 = "0a0652d9a2609a968c14be1a9ea00bf4b1d64e2e1f53a1b51b6fff3a6e829273",
        strip_prefix = "hyper-0.10.16",
        build_file = Label("//remote/remote:BUILD.hyper-0.10.16.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hyper__0_14_20",
        url = "https://crates.io/api/v1/crates/hyper/0.14.20/download",
        type = "tar.gz",
        sha256 = "02c929dc5c39e335a03c405292728118860721b10190d98c2a0f0efd5baafbac",
        strip_prefix = "hyper-0.14.20",
        build_file = Label("//remote/remote:BUILD.hyper-0.14.20.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hyper_rustls__0_23_0",
        url = "https://crates.io/api/v1/crates/hyper-rustls/0.23.0/download",
        type = "tar.gz",
        sha256 = "d87c48c02e0dc5e3b849a2041db3029fd066650f8f717c07bf8ed78ccb895cac",
        strip_prefix = "hyper-rustls-0.23.0",
        build_file = Label("//remote/remote:BUILD.hyper-rustls-0.23.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hyper_tls__0_5_0",
        url = "https://crates.io/api/v1/crates/hyper-tls/0.5.0/download",
        type = "tar.gz",
        sha256 = "d6183ddfa99b85da61a140bea0efc93fdf56ceaa041b37d553518030827f9905",
        strip_prefix = "hyper-tls-0.5.0",
        build_file = Label("//remote/remote:BUILD.hyper-tls-0.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ident_case__1_0_1",
        url = "https://crates.io/api/v1/crates/ident_case/1.0.1/download",
        type = "tar.gz",
        sha256 = "b9e0384b61958566e926dc50660321d12159025e767c18e043daf26b70104c39",
        strip_prefix = "ident_case-1.0.1",
        build_file = Label("//remote/remote:BUILD.ident_case-1.0.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__idna__0_1_5",
        url = "https://crates.io/api/v1/crates/idna/0.1.5/download",
        type = "tar.gz",
        sha256 = "38f09e0f0b1fb55fdee1f17470ad800da77af5186a1a76c026b679358b7e844e",
        strip_prefix = "idna-0.1.5",
        build_file = Label("//remote/remote:BUILD.idna-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__idna__0_2_3",
        url = "https://crates.io/api/v1/crates/idna/0.2.3/download",
        type = "tar.gz",
        sha256 = "418a0a6fab821475f634efe3ccc45c013f742efe03d853e8d3355d5cb850ecf8",
        strip_prefix = "idna-0.2.3",
        build_file = Label("//remote/remote:BUILD.idna-0.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__indexmap__1_9_1",
        url = "https://crates.io/api/v1/crates/indexmap/1.9.1/download",
        type = "tar.gz",
        sha256 = "10a35a97730320ffe8e2d410b5d3b69279b98d2c14bdb8b70ea89ecf7888d41e",
        strip_prefix = "indexmap-1.9.1",
        build_file = Label("//remote/remote:BUILD.indexmap-1.9.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__input_buffer__0_4_0",
        url = "https://crates.io/api/v1/crates/input_buffer/0.4.0/download",
        type = "tar.gz",
        sha256 = "f97967975f448f1a7ddb12b0bc41069d09ed6a1c161a92687e057325db35d413",
        strip_prefix = "input_buffer-0.4.0",
        build_file = Label("//remote/remote:BUILD.input_buffer-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__instant__0_1_12",
        url = "https://crates.io/api/v1/crates/instant/0.1.12/download",
        type = "tar.gz",
        sha256 = "7a5bbe824c507c5da5956355e86a746d82e0e1464f65d862cc5e71da70e94b2c",
        strip_prefix = "instant-0.1.12",
        build_file = Label("//remote/remote:BUILD.instant-0.1.12.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ipnet__2_5_0",
        url = "https://crates.io/api/v1/crates/ipnet/2.5.0/download",
        type = "tar.gz",
        sha256 = "879d54834c8c76457ef4293a689b2a8c59b076067ad77b15efafbb05f92a592b",
        strip_prefix = "ipnet-2.5.0",
        build_file = Label("//remote/remote:BUILD.ipnet-2.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__itoa__0_4_8",
        url = "https://crates.io/api/v1/crates/itoa/0.4.8/download",
        type = "tar.gz",
        sha256 = "b71991ff56294aa922b450139ee08b3bfc70982c6b2c7562771375cf73542dd4",
        strip_prefix = "itoa-0.4.8",
        build_file = Label("//remote/remote:BUILD.itoa-0.4.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__itoa__1_0_2",
        url = "https://crates.io/api/v1/crates/itoa/1.0.2/download",
        type = "tar.gz",
        sha256 = "112c678d4050afce233f4f2852bb2eb519230b3cf12f33585275537d7e41578d",
        strip_prefix = "itoa-1.0.2",
        build_file = Label("//remote/remote:BUILD.itoa-1.0.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__js_sys__0_3_59",
        url = "https://crates.io/api/v1/crates/js-sys/0.3.59/download",
        type = "tar.gz",
        sha256 = "258451ab10b34f8af53416d1fdab72c22e805f0c92a1136d59470ec0b11138b2",
        strip_prefix = "js-sys-0.3.59",
        build_file = Label("//remote/remote:BUILD.js-sys-0.3.59.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__jwt__0_16_0",
        url = "https://crates.io/api/v1/crates/jwt/0.16.0/download",
        type = "tar.gz",
        sha256 = "6204285f77fe7d9784db3fdc449ecce1a0114927a51d5a41c4c7a292011c015f",
        strip_prefix = "jwt-0.16.0",
        build_file = Label("//remote/remote:BUILD.jwt-0.16.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__kernel32_sys__0_2_2",
        url = "https://crates.io/api/v1/crates/kernel32-sys/0.2.2/download",
        type = "tar.gz",
        sha256 = "7507624b29483431c0ba2d82aece8ca6cdba9382bff4ddd0f7490560c056098d",
        strip_prefix = "kernel32-sys-0.2.2",
        build_file = Label("//remote/remote:BUILD.kernel32-sys-0.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__language_tags__0_2_2",
        url = "https://crates.io/api/v1/crates/language-tags/0.2.2/download",
        type = "tar.gz",
        sha256 = "a91d884b6667cd606bb5a69aa0c99ba811a115fc68915e7056ec08a46e93199a",
        strip_prefix = "language-tags-0.2.2",
        build_file = Label("//remote/remote:BUILD.language-tags-0.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__lazy_static__1_4_0",
        url = "https://crates.io/api/v1/crates/lazy_static/1.4.0/download",
        type = "tar.gz",
        sha256 = "e2abad23fbc42b3700f2f279844dc832adb2b2eb069b2df918f455c4e18cc646",
        strip_prefix = "lazy_static-1.4.0",
        build_file = Label("//remote/remote:BUILD.lazy_static-1.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__libc__0_2_126",
        url = "https://crates.io/api/v1/crates/libc/0.2.126/download",
        type = "tar.gz",
        sha256 = "349d5a591cd28b49e1d1037471617a32ddcda5731b99419008085f72d5a53836",
        strip_prefix = "libc-0.2.126",
        build_file = Label("//remote/remote:BUILD.libc-0.2.126.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__linked_hash_map__0_5_6",
        url = "https://crates.io/api/v1/crates/linked-hash-map/0.5.6/download",
        type = "tar.gz",
        sha256 = "0717cef1bc8b636c6e1c1bbdefc09e6322da8a9321966e8928ef80d20f7f770f",
        strip_prefix = "linked-hash-map-0.5.6",
        build_file = Label("//remote/remote:BUILD.linked-hash-map-0.5.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__lock_api__0_4_7",
        url = "https://crates.io/api/v1/crates/lock_api/0.4.7/download",
        type = "tar.gz",
        sha256 = "327fa5b6a6940e4699ec49a9beae1ea4845c6bab9314e4f84ac68742139d8c53",
        strip_prefix = "lock_api-0.4.7",
        build_file = Label("//remote/remote:BUILD.lock_api-0.4.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__log__0_3_9",
        url = "https://crates.io/api/v1/crates/log/0.3.9/download",
        type = "tar.gz",
        sha256 = "e19e8d5c34a3e0e2223db8e060f9e8264aeeb5c5fc64a4ee9965c062211c024b",
        strip_prefix = "log-0.3.9",
        build_file = Label("//remote/remote:BUILD.log-0.3.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__log__0_4_17",
        url = "https://crates.io/api/v1/crates/log/0.4.17/download",
        type = "tar.gz",
        sha256 = "abb12e687cfb44aa40f41fc3978ef76448f9b6038cad6aef4259d3c095a2382e",
        strip_prefix = "log-0.4.17",
        build_file = Label("//remote/remote:BUILD.log-0.4.17.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mac__0_1_1",
        url = "https://crates.io/api/v1/crates/mac/0.1.1/download",
        type = "tar.gz",
        sha256 = "c41e0c4fef86961ac6d6f8a82609f55f31b05e4fce149ac5710e439df7619ba4",
        strip_prefix = "mac-0.1.1",
        build_file = Label("//remote/remote:BUILD.mac-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__markup5ever__0_11_0",
        url = "https://crates.io/api/v1/crates/markup5ever/0.11.0/download",
        type = "tar.gz",
        sha256 = "7a2629bb1404f3d34c2e921f21fd34ba00b206124c81f65c50b43b6aaefeb016",
        strip_prefix = "markup5ever-0.11.0",
        build_file = Label("//remote/remote:BUILD.markup5ever-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__matches__0_1_9",
        url = "https://crates.io/api/v1/crates/matches/0.1.9/download",
        type = "tar.gz",
        sha256 = "a3e378b66a060d48947b590737b30a1be76706c8dd7b8ba0f2fe3989c68a853f",
        strip_prefix = "matches-0.1.9",
        build_file = Label("//remote/remote:BUILD.matches-0.1.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__memchr__0_1_11",
        url = "https://crates.io/api/v1/crates/memchr/0.1.11/download",
        type = "tar.gz",
        sha256 = "d8b629fb514376c675b98c1421e80b151d3817ac42d7c667717d282761418d20",
        strip_prefix = "memchr-0.1.11",
        build_file = Label("//remote/remote:BUILD.memchr-0.1.11.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__memchr__2_5_0",
        url = "https://crates.io/api/v1/crates/memchr/2.5.0/download",
        type = "tar.gz",
        sha256 = "2dffe52ecf27772e601905b7522cb4ef790d2cc203488bbd0e2fe85fcb74566d",
        strip_prefix = "memchr-2.5.0",
        build_file = Label("//remote/remote:BUILD.memchr-2.5.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mime__0_2_6",
        url = "https://crates.io/api/v1/crates/mime/0.2.6/download",
        type = "tar.gz",
        sha256 = "ba626b8a6de5da682e1caa06bdb42a335aee5a84db8e5046a3e8ab17ba0a3ae0",
        strip_prefix = "mime-0.2.6",
        build_file = Label("//remote/remote:BUILD.mime-0.2.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mime__0_3_16",
        url = "https://crates.io/api/v1/crates/mime/0.3.16/download",
        type = "tar.gz",
        sha256 = "2a60c7ce501c71e03a9c9c0d35b861413ae925bd979cc7a4e30d060069aaac8d",
        strip_prefix = "mime-0.3.16",
        build_file = Label("//remote/remote:BUILD.mime-0.3.16.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mime_guess__2_0_4",
        url = "https://crates.io/api/v1/crates/mime_guess/2.0.4/download",
        type = "tar.gz",
        sha256 = "4192263c238a5f0d0c6bfd21f336a313a4ce1c450542449ca191bb657b4642ef",
        strip_prefix = "mime_guess-2.0.4",
        build_file = Label("//remote/remote:BUILD.mime_guess-2.0.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__miniz_oxide__0_5_3",
        url = "https://crates.io/api/v1/crates/miniz_oxide/0.5.3/download",
        type = "tar.gz",
        sha256 = "6f5c75688da582b8ffc1f1799e9db273f32133c49e048f614d22ec3256773ccc",
        strip_prefix = "miniz_oxide-0.5.3",
        build_file = Label("//remote/remote:BUILD.miniz_oxide-0.5.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mio__0_8_4",
        url = "https://crates.io/api/v1/crates/mio/0.8.4/download",
        type = "tar.gz",
        sha256 = "57ee1c23c7c63b0c9250c339ffdc69255f110b298b901b9f6c82547b7b87caaf",
        strip_prefix = "mio-0.8.4",
        build_file = Label("//remote/remote:BUILD.mio-0.8.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__mownstr__0_1_3",
        url = "https://crates.io/api/v1/crates/mownstr/0.1.3/download",
        type = "tar.gz",
        sha256 = "76aacdf8f9850a9db34e33e35abfc17a29b9577d0eb2cbfaeb734662cacca5b3",
        strip_prefix = "mownstr-0.1.3",
        build_file = Label("//remote/remote:BUILD.mownstr-0.1.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__multipart__0_18_0",
        url = "https://crates.io/api/v1/crates/multipart/0.18.0/download",
        type = "tar.gz",
        sha256 = "00dec633863867f29cb39df64a397cdf4a6354708ddd7759f70c7fb51c5f9182",
        strip_prefix = "multipart-0.18.0",
        build_file = Label("//remote/remote:BUILD.multipart-0.18.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__native_tls__0_2_10",
        url = "https://crates.io/api/v1/crates/native-tls/0.2.10/download",
        type = "tar.gz",
        sha256 = "fd7e2f3618557f980e0b17e8856252eee3c97fa12c54dff0ca290fb6266ca4a9",
        strip_prefix = "native-tls-0.2.10",
        build_file = Label("//remote/remote:BUILD.native-tls-0.2.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__new_debug_unreachable__1_0_4",
        url = "https://crates.io/api/v1/crates/new_debug_unreachable/1.0.4/download",
        type = "tar.gz",
        sha256 = "e4a24736216ec316047a1fc4252e27dabb04218aa4a3f37c6e7ddbf1f9782b54",
        strip_prefix = "new_debug_unreachable-1.0.4",
        build_file = Label("//remote/remote:BUILD.new_debug_unreachable-1.0.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__nodrop__0_1_14",
        url = "https://crates.io/api/v1/crates/nodrop/0.1.14/download",
        type = "tar.gz",
        sha256 = "72ef4a56884ca558e5ddb05a1d1e7e1bfd9a68d9ed024c21704cc98872dae1bb",
        strip_prefix = "nodrop-0.1.14",
        build_file = Label("//remote/remote:BUILD.nodrop-0.1.14.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num__0_3_1",
        url = "https://crates.io/api/v1/crates/num/0.3.1/download",
        type = "tar.gz",
        sha256 = "8b7a8e9be5e039e2ff869df49155f1c06bd01ade2117ec783e56ab0932b67a8f",
        strip_prefix = "num-0.3.1",
        build_file = Label("//remote/remote:BUILD.num-0.3.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_bigint__0_3_3",
        url = "https://crates.io/api/v1/crates/num-bigint/0.3.3/download",
        type = "tar.gz",
        sha256 = "5f6f7833f2cbf2360a6cfd58cd41a53aa7a90bd4c202f5b1c7dd2ed73c57b2c3",
        strip_prefix = "num-bigint-0.3.3",
        build_file = Label("//remote/remote:BUILD.num-bigint-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_bigint__0_4_3",
        url = "https://crates.io/api/v1/crates/num-bigint/0.4.3/download",
        type = "tar.gz",
        sha256 = "f93ab6289c7b344a8a9f60f88d80aa20032336fe78da341afc91c8a2341fc75f",
        strip_prefix = "num-bigint-0.4.3",
        build_file = Label("//remote/remote:BUILD.num-bigint-0.4.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_complex__0_3_1",
        url = "https://crates.io/api/v1/crates/num-complex/0.3.1/download",
        type = "tar.gz",
        sha256 = "747d632c0c558b87dbabbe6a82f3b4ae03720d0646ac5b7b4dae89394be5f2c5",
        strip_prefix = "num-complex-0.3.1",
        build_file = Label("//remote/remote:BUILD.num-complex-0.3.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_integer__0_1_45",
        url = "https://crates.io/api/v1/crates/num-integer/0.1.45/download",
        type = "tar.gz",
        sha256 = "225d3389fb3509a24c93f5c29eb6bde2586b98d9f016636dff58d7c6f7569cd9",
        strip_prefix = "num-integer-0.1.45",
        build_file = Label("//remote/remote:BUILD.num-integer-0.1.45.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_iter__0_1_43",
        url = "https://crates.io/api/v1/crates/num-iter/0.1.43/download",
        type = "tar.gz",
        sha256 = "7d03e6c028c5dc5cac6e2dec0efda81fc887605bb3d884578bb6d6bf7514e252",
        strip_prefix = "num-iter-0.1.43",
        build_file = Label("//remote/remote:BUILD.num-iter-0.1.43.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_rational__0_3_2",
        url = "https://crates.io/api/v1/crates/num-rational/0.3.2/download",
        type = "tar.gz",
        sha256 = "12ac428b1cb17fce6f731001d307d351ec70a6d202fc2e60f7d4c5e42d8f4f07",
        strip_prefix = "num-rational-0.3.2",
        build_file = Label("//remote/remote:BUILD.num-rational-0.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_traits__0_2_15",
        url = "https://crates.io/api/v1/crates/num-traits/0.2.15/download",
        type = "tar.gz",
        sha256 = "578ede34cf02f8924ab9447f50c28075b4d3e5b269972345e7e0372b38c6cdcd",
        strip_prefix = "num-traits-0.2.15",
        build_file = Label("//remote/remote:BUILD.num-traits-0.2.15.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_cpus__1_13_1",
        url = "https://crates.io/api/v1/crates/num_cpus/1.13.1/download",
        type = "tar.gz",
        sha256 = "19e64526ebdee182341572e50e9ad03965aa510cd94427a4549448f285e957a1",
        strip_prefix = "num_cpus-1.13.1",
        build_file = Label("//remote/remote:BUILD.num_cpus-1.13.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__oauth2__4_2_3",
        url = "https://crates.io/api/v1/crates/oauth2/4.2.3/download",
        type = "tar.gz",
        sha256 = "6d62c436394991641b970a92e23e8eeb4eb9bca74af4f5badc53bcd568daadbd",
        strip_prefix = "oauth2-4.2.3",
        build_file = Label("//remote/remote:BUILD.oauth2-4.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__object__0_29_0",
        url = "https://crates.io/api/v1/crates/object/0.29.0/download",
        type = "tar.gz",
        sha256 = "21158b2c33aa6d4561f1c0a6ea283ca92bc54802a93b263e910746d679a7eb53",
        strip_prefix = "object-0.29.0",
        build_file = Label("//remote/remote:BUILD.object-0.29.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__once_cell__1_13_0",
        url = "https://crates.io/api/v1/crates/once_cell/1.13.0/download",
        type = "tar.gz",
        sha256 = "18a6dbe30758c9f83eb00cbea4ac95966305f5a7772f3f42ebfc7fc7eddbd8e1",
        strip_prefix = "once_cell-1.13.0",
        build_file = Label("//remote/remote:BUILD.once_cell-1.13.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__opaque_debug__0_2_3",
        url = "https://crates.io/api/v1/crates/opaque-debug/0.2.3/download",
        type = "tar.gz",
        sha256 = "2839e79665f131bdb5782e51f2c6c9599c133c6098982a54c794358bf432529c",
        strip_prefix = "opaque-debug-0.2.3",
        build_file = Label("//remote/remote:BUILD.opaque-debug-0.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__opaque_debug__0_3_0",
        url = "https://crates.io/api/v1/crates/opaque-debug/0.3.0/download",
        type = "tar.gz",
        sha256 = "624a8340c38c1b80fd549087862da4ba43e08858af025b236e509b6649fc13d5",
        strip_prefix = "opaque-debug-0.3.0",
        build_file = Label("//remote/remote:BUILD.opaque-debug-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__openssl__0_10_41",
        url = "https://crates.io/api/v1/crates/openssl/0.10.41/download",
        type = "tar.gz",
        sha256 = "618febf65336490dfcf20b73f885f5651a0c89c64c2d4a8c3662585a70bf5bd0",
        strip_prefix = "openssl-0.10.41",
        build_file = Label("//remote/remote:BUILD.openssl-0.10.41.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__openssl_macros__0_1_0",
        url = "https://crates.io/api/v1/crates/openssl-macros/0.1.0/download",
        type = "tar.gz",
        sha256 = "b501e44f11665960c7e7fcf062c7d96a14ade4aa98116c004b2e37b5be7d736c",
        strip_prefix = "openssl-macros-0.1.0",
        build_file = Label("//remote/remote:BUILD.openssl-macros-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__openssl_probe__0_1_5",
        url = "https://crates.io/api/v1/crates/openssl-probe/0.1.5/download",
        type = "tar.gz",
        sha256 = "ff011a302c396a5197692431fc1948019154afc178baf7d8e37367442a4601cf",
        strip_prefix = "openssl-probe-0.1.5",
        build_file = Label("//remote/remote:BUILD.openssl-probe-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__openssl_sys__0_9_75",
        url = "https://crates.io/api/v1/crates/openssl-sys/0.9.75/download",
        type = "tar.gz",
        sha256 = "e5f9bd0c2710541a3cda73d6f9ac4f1b240de4ae261065d309dbe73d9dceb42f",
        strip_prefix = "openssl-sys-0.9.75",
        build_file = Label("//remote/remote:BUILD.openssl-sys-0.9.75.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__oxilangtag__0_1_3",
        url = "https://crates.io/api/v1/crates/oxilangtag/0.1.3/download",
        type = "tar.gz",
        sha256 = "8d91edf4fbb970279443471345a4e8c491bf05bb283b3e6c88e4e606fd8c181b",
        strip_prefix = "oxilangtag-0.1.3",
        build_file = Label("//remote/remote:BUILD.oxilangtag-0.1.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__oxiri__0_2_2",
        url = "https://crates.io/api/v1/crates/oxiri/0.2.2/download",
        type = "tar.gz",
        sha256 = "bb175ec8981211357b7b379869c2f8d555881c55ea62311428ec0de46d89bd5c",
        strip_prefix = "oxiri-0.2.2",
        build_file = Label("//remote/remote:BUILD.oxiri-0.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__parking_lot__0_12_1",
        url = "https://crates.io/api/v1/crates/parking_lot/0.12.1/download",
        type = "tar.gz",
        sha256 = "3742b2c103b9f06bc9fff0a37ff4912935851bee6d36f3c02bcc755bcfec228f",
        strip_prefix = "parking_lot-0.12.1",
        build_file = Label("//remote/remote:BUILD.parking_lot-0.12.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__parking_lot_core__0_9_3",
        url = "https://crates.io/api/v1/crates/parking_lot_core/0.9.3/download",
        type = "tar.gz",
        sha256 = "09a279cbf25cb0757810394fbc1e359949b59e348145c643a939a525692e6929",
        strip_prefix = "parking_lot_core-0.9.3",
        build_file = Label("//remote/remote:BUILD.parking_lot_core-0.9.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__parse_zoneinfo__0_1_1",
        url = "https://crates.io/api/v1/crates/parse-zoneinfo/0.1.1/download",
        type = "tar.gz",
        sha256 = "f4ee19a3656dadae35a33467f9714f1228dd34766dbe49e10e656b5296867aea",
        strip_prefix = "parse-zoneinfo-0.1.1",
        build_file = Label("//remote/remote:BUILD.parse-zoneinfo-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__parse_zoneinfo__0_3_0",
        url = "https://crates.io/api/v1/crates/parse-zoneinfo/0.3.0/download",
        type = "tar.gz",
        sha256 = "c705f256449c60da65e11ff6626e0c16a0a0b96aaa348de61376b249bc340f41",
        strip_prefix = "parse-zoneinfo-0.3.0",
        build_file = Label("//remote/remote:BUILD.parse-zoneinfo-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__percent_encoding__1_0_1",
        url = "https://crates.io/api/v1/crates/percent-encoding/1.0.1/download",
        type = "tar.gz",
        sha256 = "31010dd2e1ac33d5b46a5b413495239882813e0369f8ed8a5e266f173602f831",
        strip_prefix = "percent-encoding-1.0.1",
        build_file = Label("//remote/remote:BUILD.percent-encoding-1.0.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__percent_encoding__2_1_0",
        url = "https://crates.io/api/v1/crates/percent-encoding/2.1.0/download",
        type = "tar.gz",
        sha256 = "d4fd5641d01c8f18a23da7b6fe29298ff4b55afcccdf78973b24cf3175fee32e",
        strip_prefix = "percent-encoding-2.1.0",
        build_file = Label("//remote/remote:BUILD.percent-encoding-2.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__petgraph__0_6_2",
        url = "https://crates.io/api/v1/crates/petgraph/0.6.2/download",
        type = "tar.gz",
        sha256 = "e6d5014253a1331579ce62aa67443b4a658c5e7dd03d4bc6d302b94474888143",
        strip_prefix = "petgraph-0.6.2",
        build_file = Label("//remote/remote:BUILD.petgraph-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf__0_10_1",
        url = "https://crates.io/api/v1/crates/phf/0.10.1/download",
        type = "tar.gz",
        sha256 = "fabbf1ead8a5bcbc20f5f8b939ee3f5b0f6f281b6ad3468b84656b658b455259",
        strip_prefix = "phf-0.10.1",
        build_file = Label("//remote/remote:BUILD.phf-0.10.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf__0_11_0",
        url = "https://crates.io/api/v1/crates/phf/0.11.0/download",
        type = "tar.gz",
        sha256 = "4724fa946c8d1e7cd881bd3dbee63ce32fc1e9e191e35786b3dc1320a3f68131",
        strip_prefix = "phf-0.11.0",
        build_file = Label("//remote/remote:BUILD.phf-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf__0_8_0",
        url = "https://crates.io/api/v1/crates/phf/0.8.0/download",
        type = "tar.gz",
        sha256 = "3dfb61232e34fcb633f43d12c58f83c1df82962dcdfa565a4e866ffc17dafe12",
        strip_prefix = "phf-0.8.0",
        build_file = Label("//remote/remote:BUILD.phf-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_codegen__0_10_0",
        url = "https://crates.io/api/v1/crates/phf_codegen/0.10.0/download",
        type = "tar.gz",
        sha256 = "4fb1c3a8bc4dd4e5cfce29b44ffc14bedd2ee294559a294e2a4d4c9e9a6a13cd",
        strip_prefix = "phf_codegen-0.10.0",
        build_file = Label("//remote/remote:BUILD.phf_codegen-0.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_codegen__0_11_0",
        url = "https://crates.io/api/v1/crates/phf_codegen/0.11.0/download",
        type = "tar.gz",
        sha256 = "32ba0c43d7a1b6492b2924a62290cfd83987828af037b0743b38e6ab092aee58",
        strip_prefix = "phf_codegen-0.11.0",
        build_file = Label("//remote/remote:BUILD.phf_codegen-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_codegen__0_8_0",
        url = "https://crates.io/api/v1/crates/phf_codegen/0.8.0/download",
        type = "tar.gz",
        sha256 = "cbffee61585b0411840d3ece935cce9cb6321f01c45477d30066498cd5e1a815",
        strip_prefix = "phf_codegen-0.8.0",
        build_file = Label("//remote/remote:BUILD.phf_codegen-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_generator__0_10_0",
        url = "https://crates.io/api/v1/crates/phf_generator/0.10.0/download",
        type = "tar.gz",
        sha256 = "5d5285893bb5eb82e6aaf5d59ee909a06a16737a8970984dd7746ba9283498d6",
        strip_prefix = "phf_generator-0.10.0",
        build_file = Label("//remote/remote:BUILD.phf_generator-0.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_generator__0_11_0",
        url = "https://crates.io/api/v1/crates/phf_generator/0.11.0/download",
        type = "tar.gz",
        sha256 = "5b450720b6f75cfbfabc195814bd3765f337a4f9a83186f8537297cac12f6705",
        strip_prefix = "phf_generator-0.11.0",
        build_file = Label("//remote/remote:BUILD.phf_generator-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_generator__0_8_0",
        url = "https://crates.io/api/v1/crates/phf_generator/0.8.0/download",
        type = "tar.gz",
        sha256 = "17367f0cc86f2d25802b2c26ee58a7b23faeccf78a396094c13dced0d0182526",
        strip_prefix = "phf_generator-0.8.0",
        build_file = Label("//remote/remote:BUILD.phf_generator-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_macros__0_8_0",
        url = "https://crates.io/api/v1/crates/phf_macros/0.8.0/download",
        type = "tar.gz",
        sha256 = "7f6fde18ff429ffc8fe78e2bf7f8b7a5a5a6e2a8b58bc5a9ac69198bbda9189c",
        strip_prefix = "phf_macros-0.8.0",
        build_file = Label("//remote/remote:BUILD.phf_macros-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_shared__0_10_0",
        url = "https://crates.io/api/v1/crates/phf_shared/0.10.0/download",
        type = "tar.gz",
        sha256 = "b6796ad771acdc0123d2a88dc428b5e38ef24456743ddb1744ed628f9815c096",
        strip_prefix = "phf_shared-0.10.0",
        build_file = Label("//remote/remote:BUILD.phf_shared-0.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_shared__0_11_0",
        url = "https://crates.io/api/v1/crates/phf_shared/0.11.0/download",
        type = "tar.gz",
        sha256 = "9dd5609d4b2df87167f908a32e1b146ce309c16cf35df76bc11f440b756048e4",
        strip_prefix = "phf_shared-0.11.0",
        build_file = Label("//remote/remote:BUILD.phf_shared-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__phf_shared__0_8_0",
        url = "https://crates.io/api/v1/crates/phf_shared/0.8.0/download",
        type = "tar.gz",
        sha256 = "c00cf8b9eafe68dde5e9eaa2cef8ee84a9336a47d566ec55ca16589633b65af7",
        strip_prefix = "phf_shared-0.8.0",
        build_file = Label("//remote/remote:BUILD.phf_shared-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__pin_project__1_0_11",
        url = "https://crates.io/api/v1/crates/pin-project/1.0.11/download",
        type = "tar.gz",
        sha256 = "78203e83c48cffbe01e4a2d35d566ca4de445d79a85372fc64e378bfc812a260",
        strip_prefix = "pin-project-1.0.11",
        build_file = Label("//remote/remote:BUILD.pin-project-1.0.11.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__pin_project_internal__1_0_11",
        url = "https://crates.io/api/v1/crates/pin-project-internal/1.0.11/download",
        type = "tar.gz",
        sha256 = "710faf75e1b33345361201d36d04e98ac1ed8909151a017ed384700836104c74",
        strip_prefix = "pin-project-internal-1.0.11",
        build_file = Label("//remote/remote:BUILD.pin-project-internal-1.0.11.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__pin_project_lite__0_2_9",
        url = "https://crates.io/api/v1/crates/pin-project-lite/0.2.9/download",
        type = "tar.gz",
        sha256 = "e0a7ae3ac2f1173085d398531c705756c94a4c56843785df85a60c1a0afac116",
        strip_prefix = "pin-project-lite-0.2.9",
        build_file = Label("//remote/remote:BUILD.pin-project-lite-0.2.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__pin_utils__0_1_0",
        url = "https://crates.io/api/v1/crates/pin-utils/0.1.0/download",
        type = "tar.gz",
        sha256 = "8b870d8c151b6f2fb93e84a13146138f05d02ed11c7e7c54f8826aaaf7c9f184",
        strip_prefix = "pin-utils-0.1.0",
        build_file = Label("//remote/remote:BUILD.pin-utils-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__pkg_config__0_3_25",
        url = "https://crates.io/api/v1/crates/pkg-config/0.3.25/download",
        type = "tar.gz",
        sha256 = "1df8c4ec4b0627e53bdf214615ad287367e482558cf84b109250b37464dc03ae",
        strip_prefix = "pkg-config-0.3.25",
        build_file = Label("//remote/remote:BUILD.pkg-config-0.3.25.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ppv_lite86__0_2_16",
        url = "https://crates.io/api/v1/crates/ppv-lite86/0.2.16/download",
        type = "tar.gz",
        sha256 = "eb9f9e6e233e5c4a35559a617bf40a4ec447db2e84c20b55a6f83167b7e57872",
        strip_prefix = "ppv-lite86-0.2.16",
        build_file = Label("//remote/remote:BUILD.ppv-lite86-0.2.16.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__precomputed_hash__0_1_1",
        url = "https://crates.io/api/v1/crates/precomputed-hash/0.1.1/download",
        type = "tar.gz",
        sha256 = "925383efa346730478fb4838dbe9137d2a47675ad789c546d150a6e1dd4ab31c",
        strip_prefix = "precomputed-hash-0.1.1",
        build_file = Label("//remote/remote:BUILD.precomputed-hash-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__proc_macro_error__1_0_4",
        url = "https://crates.io/api/v1/crates/proc-macro-error/1.0.4/download",
        type = "tar.gz",
        sha256 = "da25490ff9892aab3fcf7c36f08cfb902dd3e71ca0f9f9517bea02a73a5ce38c",
        strip_prefix = "proc-macro-error-1.0.4",
        build_file = Label("//remote/remote:BUILD.proc-macro-error-1.0.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__proc_macro_error_attr__1_0_4",
        url = "https://crates.io/api/v1/crates/proc-macro-error-attr/1.0.4/download",
        type = "tar.gz",
        sha256 = "a1be40180e52ecc98ad80b184934baf3d0d29f979574e439af5a55274b35f869",
        strip_prefix = "proc-macro-error-attr-1.0.4",
        build_file = Label("//remote/remote:BUILD.proc-macro-error-attr-1.0.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__proc_macro_hack__0_5_19",
        url = "https://crates.io/api/v1/crates/proc-macro-hack/0.5.19/download",
        type = "tar.gz",
        sha256 = "dbf0c48bc1d91375ae5c3cd81e3722dff1abcf81a30960240640d223f59fe0e5",
        strip_prefix = "proc-macro-hack-0.5.19",
        build_file = Label("//remote/remote:BUILD.proc-macro-hack-0.5.19.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__proc_macro2__0_4_30",
        url = "https://crates.io/api/v1/crates/proc-macro2/0.4.30/download",
        type = "tar.gz",
        sha256 = "cf3d2011ab5c909338f7887f4fc896d35932e29146c12c8d01da6b22a80ba759",
        strip_prefix = "proc-macro2-0.4.30",
        build_file = Label("//remote/remote:BUILD.proc-macro2-0.4.30.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__proc_macro2__1_0_42",
        url = "https://crates.io/api/v1/crates/proc-macro2/1.0.42/download",
        type = "tar.gz",
        sha256 = "c278e965f1d8cf32d6e0e96de3d3e79712178ae67986d9cf9151f51e95aac89b",
        strip_prefix = "proc-macro2-1.0.42",
        build_file = Label("//remote/remote:BUILD.proc-macro2-1.0.42.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__quick_error__1_2_3",
        url = "https://crates.io/api/v1/crates/quick-error/1.2.3/download",
        type = "tar.gz",
        sha256 = "a1d01941d82fa2ab50be1e79e6714289dd7cde78eba4c074bc5a4374f650dfe0",
        strip_prefix = "quick-error-1.2.3",
        build_file = Label("//remote/remote:BUILD.quick-error-1.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__quote__0_6_13",
        url = "https://crates.io/api/v1/crates/quote/0.6.13/download",
        type = "tar.gz",
        sha256 = "6ce23b6b870e8f94f81fb0a363d65d86675884b34a09043c81e5562f11c1f8e1",
        strip_prefix = "quote-0.6.13",
        build_file = Label("//remote/remote:BUILD.quote-0.6.13.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__quote__1_0_20",
        url = "https://crates.io/api/v1/crates/quote/1.0.20/download",
        type = "tar.gz",
        sha256 = "3bcdf212e9776fbcb2d23ab029360416bb1706b1aea2d1a5ba002727cbcab804",
        strip_prefix = "quote-1.0.20",
        build_file = Label("//remote/remote:BUILD.quote-1.0.20.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand__0_6_5",
        url = "https://crates.io/api/v1/crates/rand/0.6.5/download",
        type = "tar.gz",
        sha256 = "6d71dacdc3c88c1fde3885a3be3fbab9f35724e6ce99467f7d9c5026132184ca",
        strip_prefix = "rand-0.6.5",
        build_file = Label("//remote/remote:BUILD.rand-0.6.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand__0_7_3",
        url = "https://crates.io/api/v1/crates/rand/0.7.3/download",
        type = "tar.gz",
        sha256 = "6a6b1679d49b24bbfe0c803429aa1874472f50d9b363131f0e89fc356b544d03",
        strip_prefix = "rand-0.7.3",
        build_file = Label("//remote/remote:BUILD.rand-0.7.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand__0_8_5",
        url = "https://crates.io/api/v1/crates/rand/0.8.5/download",
        type = "tar.gz",
        sha256 = "34af8d1a0e25924bc5b7c43c079c942339d8f0a8b57c39049bef581b46327404",
        strip_prefix = "rand-0.8.5",
        build_file = Label("//remote/remote:BUILD.rand-0.8.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_chacha__0_1_1",
        url = "https://crates.io/api/v1/crates/rand_chacha/0.1.1/download",
        type = "tar.gz",
        sha256 = "556d3a1ca6600bfcbab7c7c91ccb085ac7fbbcd70e008a98742e7847f4f7bcef",
        strip_prefix = "rand_chacha-0.1.1",
        build_file = Label("//remote/remote:BUILD.rand_chacha-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_chacha__0_2_2",
        url = "https://crates.io/api/v1/crates/rand_chacha/0.2.2/download",
        type = "tar.gz",
        sha256 = "f4c8ed856279c9737206bf725bf36935d8666ead7aa69b52be55af369d193402",
        strip_prefix = "rand_chacha-0.2.2",
        build_file = Label("//remote/remote:BUILD.rand_chacha-0.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_chacha__0_3_1",
        url = "https://crates.io/api/v1/crates/rand_chacha/0.3.1/download",
        type = "tar.gz",
        sha256 = "e6c10a63a0fa32252be49d21e7709d4d4baf8d231c2dbce1eaa8141b9b127d88",
        strip_prefix = "rand_chacha-0.3.1",
        build_file = Label("//remote/remote:BUILD.rand_chacha-0.3.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_core__0_3_1",
        url = "https://crates.io/api/v1/crates/rand_core/0.3.1/download",
        type = "tar.gz",
        sha256 = "7a6fdeb83b075e8266dcc8762c22776f6877a63111121f5f8c7411e5be7eed4b",
        strip_prefix = "rand_core-0.3.1",
        build_file = Label("//remote/remote:BUILD.rand_core-0.3.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_core__0_4_2",
        url = "https://crates.io/api/v1/crates/rand_core/0.4.2/download",
        type = "tar.gz",
        sha256 = "9c33a3c44ca05fa6f1807d8e6743f3824e8509beca625669633be0acbdf509dc",
        strip_prefix = "rand_core-0.4.2",
        build_file = Label("//remote/remote:BUILD.rand_core-0.4.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_core__0_5_1",
        url = "https://crates.io/api/v1/crates/rand_core/0.5.1/download",
        type = "tar.gz",
        sha256 = "90bde5296fc891b0cef12a6d03ddccc162ce7b2aff54160af9338f8d40df6d19",
        strip_prefix = "rand_core-0.5.1",
        build_file = Label("//remote/remote:BUILD.rand_core-0.5.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_core__0_6_3",
        url = "https://crates.io/api/v1/crates/rand_core/0.6.3/download",
        type = "tar.gz",
        sha256 = "d34f1408f55294453790c48b2f1ebbb1c5b4b7563eb1f418bcfcfdbb06ebb4e7",
        strip_prefix = "rand_core-0.6.3",
        build_file = Label("//remote/remote:BUILD.rand_core-0.6.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_hc__0_1_0",
        url = "https://crates.io/api/v1/crates/rand_hc/0.1.0/download",
        type = "tar.gz",
        sha256 = "7b40677c7be09ae76218dc623efbf7b18e34bced3f38883af07bb75630a21bc4",
        strip_prefix = "rand_hc-0.1.0",
        build_file = Label("//remote/remote:BUILD.rand_hc-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_hc__0_2_0",
        url = "https://crates.io/api/v1/crates/rand_hc/0.2.0/download",
        type = "tar.gz",
        sha256 = "ca3129af7b92a17112d59ad498c6f81eaf463253766b90396d39ea7a39d6613c",
        strip_prefix = "rand_hc-0.2.0",
        build_file = Label("//remote/remote:BUILD.rand_hc-0.2.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_isaac__0_1_1",
        url = "https://crates.io/api/v1/crates/rand_isaac/0.1.1/download",
        type = "tar.gz",
        sha256 = "ded997c9d5f13925be2a6fd7e66bf1872597f759fd9dd93513dd7e92e5a5ee08",
        strip_prefix = "rand_isaac-0.1.1",
        build_file = Label("//remote/remote:BUILD.rand_isaac-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_jitter__0_1_4",
        url = "https://crates.io/api/v1/crates/rand_jitter/0.1.4/download",
        type = "tar.gz",
        sha256 = "1166d5c91dc97b88d1decc3285bb0a99ed84b05cfd0bc2341bdf2d43fc41e39b",
        strip_prefix = "rand_jitter-0.1.4",
        build_file = Label("//remote/remote:BUILD.rand_jitter-0.1.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_os__0_1_3",
        url = "https://crates.io/api/v1/crates/rand_os/0.1.3/download",
        type = "tar.gz",
        sha256 = "7b75f676a1e053fc562eafbb47838d67c84801e38fc1ba459e8f180deabd5071",
        strip_prefix = "rand_os-0.1.3",
        build_file = Label("//remote/remote:BUILD.rand_os-0.1.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_pcg__0_1_2",
        url = "https://crates.io/api/v1/crates/rand_pcg/0.1.2/download",
        type = "tar.gz",
        sha256 = "abf9b09b01790cfe0364f52bf32995ea3c39f4d2dd011eac241d2914146d0b44",
        strip_prefix = "rand_pcg-0.1.2",
        build_file = Label("//remote/remote:BUILD.rand_pcg-0.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_pcg__0_2_1",
        url = "https://crates.io/api/v1/crates/rand_pcg/0.2.1/download",
        type = "tar.gz",
        sha256 = "16abd0c1b639e9eb4d7c50c0b8100b0d0f849be2349829c740fe8e6eb4816429",
        strip_prefix = "rand_pcg-0.2.1",
        build_file = Label("//remote/remote:BUILD.rand_pcg-0.2.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rand_xorshift__0_1_1",
        url = "https://crates.io/api/v1/crates/rand_xorshift/0.1.1/download",
        type = "tar.gz",
        sha256 = "cbf7e9e623549b0e21f6e97cf8ecf247c1a8fd2e8a992ae265314300b2455d5c",
        strip_prefix = "rand_xorshift-0.1.1",
        build_file = Label("//remote/remote:BUILD.rand_xorshift-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rdrand__0_4_0",
        url = "https://crates.io/api/v1/crates/rdrand/0.4.0/download",
        type = "tar.gz",
        sha256 = "678054eb77286b51581ba43620cc911abf02758c91f93f479767aed0f90458b2",
        strip_prefix = "rdrand-0.4.0",
        build_file = Label("//remote/remote:BUILD.rdrand-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__redox_syscall__0_2_16",
        url = "https://crates.io/api/v1/crates/redox_syscall/0.2.16/download",
        type = "tar.gz",
        sha256 = "fb5a58c1855b4b6819d59012155603f0b22ad30cad752600aadfcb695265519a",
        strip_prefix = "redox_syscall-0.2.16",
        build_file = Label("//remote/remote:BUILD.redox_syscall-0.2.16.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__redox_users__0_4_3",
        url = "https://crates.io/api/v1/crates/redox_users/0.4.3/download",
        type = "tar.gz",
        sha256 = "b033d837a7cf162d7993aded9304e30a83213c648b6e389db233191f891e5c2b",
        strip_prefix = "redox_users-0.4.3",
        build_file = Label("//remote/remote:BUILD.redox_users-0.4.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex__0_1_80",
        url = "https://crates.io/api/v1/crates/regex/0.1.80/download",
        type = "tar.gz",
        sha256 = "4fd4ace6a8cf7860714a2c2280d6c1f7e6a413486c13298bbc86fd3da019402f",
        strip_prefix = "regex-0.1.80",
        build_file = Label("//remote/remote:BUILD.regex-0.1.80.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex__0_2_11",
        url = "https://crates.io/api/v1/crates/regex/0.2.11/download",
        type = "tar.gz",
        sha256 = "9329abc99e39129fcceabd24cf5d85b4671ef7c29c50e972bc5afe32438ec384",
        strip_prefix = "regex-0.2.11",
        build_file = Label("//remote/remote:BUILD.regex-0.2.11.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex__1_6_0",
        url = "https://crates.io/api/v1/crates/regex/1.6.0/download",
        type = "tar.gz",
        sha256 = "4c4eb3267174b8c6c2f654116623910a0fef09c4753f8dd83db29c48a0df988b",
        strip_prefix = "regex-1.6.0",
        build_file = Label("//remote/remote:BUILD.regex-1.6.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex_automata__0_1_10",
        url = "https://crates.io/api/v1/crates/regex-automata/0.1.10/download",
        type = "tar.gz",
        sha256 = "6c230d73fb8d8c1b9c0b3135c5142a8acee3a0558fb8db5cf1cb65f8d7862132",
        strip_prefix = "regex-automata-0.1.10",
        build_file = Label("//remote/remote:BUILD.regex-automata-0.1.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex_syntax__0_3_9",
        url = "https://crates.io/api/v1/crates/regex-syntax/0.3.9/download",
        type = "tar.gz",
        sha256 = "f9ec002c35e86791825ed294b50008eea9ddfc8def4420124fbc6b08db834957",
        strip_prefix = "regex-syntax-0.3.9",
        build_file = Label("//remote/remote:BUILD.regex-syntax-0.3.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex_syntax__0_5_6",
        url = "https://crates.io/api/v1/crates/regex-syntax/0.5.6/download",
        type = "tar.gz",
        sha256 = "7d707a4fa2637f2dca2ef9fd02225ec7661fe01a53623c1e6515b6916511f7a7",
        strip_prefix = "regex-syntax-0.5.6",
        build_file = Label("//remote/remote:BUILD.regex-syntax-0.5.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex_syntax__0_6_27",
        url = "https://crates.io/api/v1/crates/regex-syntax/0.6.27/download",
        type = "tar.gz",
        sha256 = "a3f87b73ce11b1619a3c6332f45341e0047173771e8b8b73f87bfeefb7b56244",
        strip_prefix = "regex-syntax-0.6.27",
        build_file = Label("//remote/remote:BUILD.regex-syntax-0.6.27.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__remove_dir_all__0_5_3",
        url = "https://crates.io/api/v1/crates/remove_dir_all/0.5.3/download",
        type = "tar.gz",
        sha256 = "3acd125665422973a33ac9d3dd2df85edad0f4ae9b00dafb1a05e43a9f5ef8e7",
        strip_prefix = "remove_dir_all-0.5.3",
        build_file = Label("//remote/remote:BUILD.remove_dir_all-0.5.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__reqwest__0_11_11",
        url = "https://crates.io/api/v1/crates/reqwest/0.11.11/download",
        type = "tar.gz",
        sha256 = "b75aa69a3f06bbcc66ede33af2af253c6f7a86b1ca0033f60c580a27074fbf92",
        strip_prefix = "reqwest-0.11.11",
        build_file = Label("//remote/remote:BUILD.reqwest-0.11.11.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__resiter__0_4_0",
        url = "https://crates.io/api/v1/crates/resiter/0.4.0/download",
        type = "tar.gz",
        sha256 = "bd69ab1e90258b7769f0b5c46bfd802b8206d0707ced4ca4b9d5681b744de1be",
        strip_prefix = "resiter-0.4.0",
        build_file = Label("//remote/remote:BUILD.resiter-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ring__0_16_20",
        url = "https://crates.io/api/v1/crates/ring/0.16.20/download",
        type = "tar.gz",
        sha256 = "3053cf52e236a3ed746dfc745aa9cacf1b791d846bdaf412f60a8d7d6e17c8fc",
        strip_prefix = "ring-0.16.20",
        build_file = Label("//remote/remote:BUILD.ring-0.16.20.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rio_api__0_6_2",
        url = "https://crates.io/api/v1/crates/rio_api/0.6.2/download",
        type = "tar.gz",
        sha256 = "6ed96d73ad4e0de59e667b26c899930c90912cad3fec5f0291fc3171c90dacae",
        strip_prefix = "rio_api-0.6.2",
        build_file = Label("//remote/remote:BUILD.rio_api-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rio_turtle__0_6_2",
        url = "https://crates.io/api/v1/crates/rio_turtle/0.6.2/download",
        type = "tar.gz",
        sha256 = "1945ea5cf5f489bd2cbafeb705686abdc94edfa9dd88a63a25e8c5c0d38f9cc2",
        strip_prefix = "rio_turtle-0.6.2",
        build_file = Label("//remote/remote:BUILD.rio_turtle-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rust_decimal__1_25_0",
        url = "https://crates.io/api/v1/crates/rust_decimal/1.25.0/download",
        type = "tar.gz",
        sha256 = "34a3bb58e85333f1ab191bf979104b586ebd77475bc6681882825f4532dfe87c",
        strip_prefix = "rust_decimal-1.25.0",
        build_file = Label("//remote/remote:BUILD.rust_decimal-1.25.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rust_decimal_macros__1_25_0",
        url = "https://crates.io/api/v1/crates/rust_decimal_macros/1.25.0/download",
        type = "tar.gz",
        sha256 = "d1467556c7c115165aa0346bcf45bc947203bcc880efad85a09ba24ea17926c4",
        strip_prefix = "rust_decimal_macros-1.25.0",
        build_file = Label("//remote/remote:BUILD.rust_decimal_macros-1.25.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rustc_demangle__0_1_21",
        url = "https://crates.io/api/v1/crates/rustc-demangle/0.1.21/download",
        type = "tar.gz",
        sha256 = "7ef03e0a2b150c7a90d01faf6254c9c48a41e95fb2a8c2ac1c6f0d2b9aefc342",
        strip_prefix = "rustc-demangle-0.1.21",
        build_file = Label("//remote/remote:BUILD.rustc-demangle-0.1.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rustc_version__0_4_0",
        url = "https://crates.io/api/v1/crates/rustc_version/0.4.0/download",
        type = "tar.gz",
        sha256 = "bfa0f585226d2e68097d4f95d113b15b83a82e819ab25717ec0590d9584ef366",
        strip_prefix = "rustc_version-0.4.0",
        build_file = Label("//remote/remote:BUILD.rustc_version-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rustls__0_20_6",
        url = "https://crates.io/api/v1/crates/rustls/0.20.6/download",
        type = "tar.gz",
        sha256 = "5aab8ee6c7097ed6057f43c187a62418d0c05a4bd5f18b3571db50ee0f9ce033",
        strip_prefix = "rustls-0.20.6",
        build_file = Label("//remote/remote:BUILD.rustls-0.20.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rustls_pemfile__1_0_0",
        url = "https://crates.io/api/v1/crates/rustls-pemfile/1.0.0/download",
        type = "tar.gz",
        sha256 = "e7522c9de787ff061458fe9a829dc790a3f5b22dc571694fc5883f448b94d9a9",
        strip_prefix = "rustls-pemfile-1.0.0",
        build_file = Label("//remote/remote:BUILD.rustls-pemfile-1.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__rusty_money__0_4_1",
        url = "https://crates.io/api/v1/crates/rusty-money/0.4.1/download",
        type = "tar.gz",
        sha256 = "5b28f881005eac7ad8d46b6f075da5f322bd7f4f83a38720fc069694ddadd683",
        strip_prefix = "rusty-money-0.4.1",
        build_file = Label("//remote/remote:BUILD.rusty-money-0.4.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ryu__1_0_10",
        url = "https://crates.io/api/v1/crates/ryu/1.0.10/download",
        type = "tar.gz",
        sha256 = "f3f6f92acf49d1b98f7a81226834412ada05458b7364277387724a237f062695",
        strip_prefix = "ryu-1.0.10",
        build_file = Label("//remote/remote:BUILD.ryu-1.0.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__safemem__0_3_3",
        url = "https://crates.io/api/v1/crates/safemem/0.3.3/download",
        type = "tar.gz",
        sha256 = "ef703b7cb59335eae2eb93ceb664c0eb7ea6bf567079d843e09420219668e072",
        strip_prefix = "safemem-0.3.3",
        build_file = Label("//remote/remote:BUILD.safemem-0.3.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__schannel__0_1_20",
        url = "https://crates.io/api/v1/crates/schannel/0.1.20/download",
        type = "tar.gz",
        sha256 = "88d6731146462ea25d9244b2ed5fd1d716d25c52e4d54aa4fb0f3c4e9854dbe2",
        strip_prefix = "schannel-0.1.20",
        build_file = Label("//remote/remote:BUILD.schannel-0.1.20.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__scoped_tls__1_0_0",
        url = "https://crates.io/api/v1/crates/scoped-tls/1.0.0/download",
        type = "tar.gz",
        sha256 = "ea6a9290e3c9cf0f18145ef7ffa62d68ee0bf5fcd651017e586dc7fd5da448c2",
        strip_prefix = "scoped-tls-1.0.0",
        build_file = Label("//remote/remote:BUILD.scoped-tls-1.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__scopeguard__1_1_0",
        url = "https://crates.io/api/v1/crates/scopeguard/1.1.0/download",
        type = "tar.gz",
        sha256 = "d29ab0c6d3fc0ee92fe66e2d99f700eab17a8d57d1c1d3b748380fb20baa78cd",
        strip_prefix = "scopeguard-1.1.0",
        build_file = Label("//remote/remote:BUILD.scopeguard-1.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__scraper__0_13_0",
        url = "https://crates.io/api/v1/crates/scraper/0.13.0/download",
        type = "tar.gz",
        sha256 = "5684396b456f3eb69ceeb34d1b5cb1a2f6acf7ca4452131efa3ba0ee2c2d0a70",
        strip_prefix = "scraper-0.13.0",
        build_file = Label("//remote/remote:BUILD.scraper-0.13.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sct__0_7_0",
        url = "https://crates.io/api/v1/crates/sct/0.7.0/download",
        type = "tar.gz",
        sha256 = "d53dcdb7c9f8158937a7981b48accfd39a43af418591a5d008c7b22b5e1b7ca4",
        strip_prefix = "sct-0.7.0",
        build_file = Label("//remote/remote:BUILD.sct-0.7.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__security_framework__2_6_1",
        url = "https://crates.io/api/v1/crates/security-framework/2.6.1/download",
        type = "tar.gz",
        sha256 = "2dc14f172faf8a0194a3aded622712b0de276821addc574fa54fc0a1167e10dc",
        strip_prefix = "security-framework-2.6.1",
        build_file = Label("//remote/remote:BUILD.security-framework-2.6.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__security_framework_sys__2_6_1",
        url = "https://crates.io/api/v1/crates/security-framework-sys/2.6.1/download",
        type = "tar.gz",
        sha256 = "0160a13a177a45bfb43ce71c01580998474f556ad854dcbca936dd2841a5c556",
        strip_prefix = "security-framework-sys-2.6.1",
        build_file = Label("//remote/remote:BUILD.security-framework-sys-2.6.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__selectors__0_22_0",
        url = "https://crates.io/api/v1/crates/selectors/0.22.0/download",
        type = "tar.gz",
        sha256 = "df320f1889ac4ba6bc0cdc9c9af7af4bd64bb927bccdf32d81140dc1f9be12fe",
        strip_prefix = "selectors-0.22.0",
        build_file = Label("//remote/remote:BUILD.selectors-0.22.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__semver__1_0_12",
        url = "https://crates.io/api/v1/crates/semver/1.0.12/download",
        type = "tar.gz",
        sha256 = "a2333e6df6d6598f2b1974829f853c2b4c5f4a6e503c10af918081aa6f8564e1",
        strip_prefix = "semver-1.0.12",
        build_file = Label("//remote/remote:BUILD.semver-1.0.12.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde__1_0_140",
        url = "https://crates.io/api/v1/crates/serde/1.0.140/download",
        type = "tar.gz",
        sha256 = "fc855a42c7967b7c369eb5860f7164ef1f6f81c20c7cc1141f2a604e18723b03",
        strip_prefix = "serde-1.0.140",
        build_file = Label("//remote/remote:BUILD.serde-1.0.140.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_xml_rs__0_5_1",
        url = "https://crates.io/api/v1/crates/serde-xml-rs/0.5.1/download",
        type = "tar.gz",
        sha256 = "65162e9059be2f6a3421ebbb4fef3e74b7d9e7c60c50a0e292c6239f19f1edfa",
        strip_prefix = "serde-xml-rs-0.5.1",
        build_file = Label("//remote/remote:BUILD.serde-xml-rs-0.5.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_derive__1_0_140",
        url = "https://crates.io/api/v1/crates/serde_derive/1.0.140/download",
        type = "tar.gz",
        sha256 = "6f2122636b9fe3b81f1cb25099fcf2d3f542cdb1d45940d56c713158884a05da",
        strip_prefix = "serde_derive-1.0.140",
        build_file = Label("//remote/remote:BUILD.serde_derive-1.0.140.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_json__1_0_82",
        url = "https://crates.io/api/v1/crates/serde_json/1.0.82/download",
        type = "tar.gz",
        sha256 = "82c2c1fdcd807d1098552c5b9a36e425e42e9fbd7c6a37a8425f390f781f7fa7",
        strip_prefix = "serde_json-1.0.82",
        build_file = Label("//remote/remote:BUILD.serde_json-1.0.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_path_to_error__0_1_7",
        url = "https://crates.io/api/v1/crates/serde_path_to_error/0.1.7/download",
        type = "tar.gz",
        sha256 = "d7868ad3b8196a8a0aea99a8220b124278ee5320a55e4fde97794b6f85b1a377",
        strip_prefix = "serde_path_to_error-0.1.7",
        build_file = Label("//remote/remote:BUILD.serde_path_to_error-0.1.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_qs__0_8_5",
        url = "https://crates.io/api/v1/crates/serde_qs/0.8.5/download",
        type = "tar.gz",
        sha256 = "c7715380eec75f029a4ef7de39a9200e0a63823176b759d055b613f5a87df6a6",
        strip_prefix = "serde_qs-0.8.5",
        build_file = Label("//remote/remote:BUILD.serde_qs-0.8.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_urlencoded__0_7_1",
        url = "https://crates.io/api/v1/crates/serde_urlencoded/0.7.1/download",
        type = "tar.gz",
        sha256 = "d3491c14715ca2294c4d6a88f15e84739788c1d030eed8c110436aafdaa2f3fd",
        strip_prefix = "serde_urlencoded-0.7.1",
        build_file = Label("//remote/remote:BUILD.serde_urlencoded-0.7.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_with__1_14_0",
        url = "https://crates.io/api/v1/crates/serde_with/1.14.0/download",
        type = "tar.gz",
        sha256 = "678b5a069e50bf00ecd22d0cd8ddf7c236f68581b03db652061ed5eb13a312ff",
        strip_prefix = "serde_with-1.14.0",
        build_file = Label("//remote/remote:BUILD.serde_with-1.14.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_with_macros__1_5_2",
        url = "https://crates.io/api/v1/crates/serde_with_macros/1.5.2/download",
        type = "tar.gz",
        sha256 = "e182d6ec6f05393cc0e5ed1bf81ad6db3a8feedf8ee515ecdd369809bcce8082",
        strip_prefix = "serde_with_macros-1.5.2",
        build_file = Label("//remote/remote:BUILD.serde_with_macros-1.5.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_yaml__0_8_26",
        url = "https://crates.io/api/v1/crates/serde_yaml/0.8.26/download",
        type = "tar.gz",
        sha256 = "578a7433b776b56a35785ed5ce9a7e777ac0598aac5a6dd1b4b18a307c7fc71b",
        strip_prefix = "serde_yaml-0.8.26",
        build_file = Label("//remote/remote:BUILD.serde_yaml-0.8.26.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__servo_arc__0_1_1",
        url = "https://crates.io/api/v1/crates/servo_arc/0.1.1/download",
        type = "tar.gz",
        sha256 = "d98238b800e0d1576d8b6e3de32827c2d74bee68bb97748dcf5071fb53965432",
        strip_prefix = "servo_arc-0.1.1",
        build_file = Label("//remote/remote:BUILD.servo_arc-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha_1__0_10_0",
        url = "https://crates.io/api/v1/crates/sha-1/0.10.0/download",
        type = "tar.gz",
        sha256 = "028f48d513f9678cda28f6e4064755b3fbb2af6acd672f2c209b62323f7aea0f",
        strip_prefix = "sha-1-0.10.0",
        build_file = Label("//remote/remote:BUILD.sha-1-0.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha_1__0_9_8",
        url = "https://crates.io/api/v1/crates/sha-1/0.9.8/download",
        type = "tar.gz",
        sha256 = "99cd6713db3cf16b6c84e06321e049a9b9f699826e16096d23bbcc44d15d51a6",
        strip_prefix = "sha-1-0.9.8",
        build_file = Label("//remote/remote:BUILD.sha-1-0.9.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha1__0_6_1",
        url = "https://crates.io/api/v1/crates/sha1/0.6.1/download",
        type = "tar.gz",
        sha256 = "c1da05c97445caa12d05e848c4a4fcbbea29e748ac28f7e80e9b010392063770",
        strip_prefix = "sha1-0.6.1",
        build_file = Label("//remote/remote:BUILD.sha1-0.6.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha1_smol__1_0_0",
        url = "https://crates.io/api/v1/crates/sha1_smol/1.0.0/download",
        type = "tar.gz",
        sha256 = "ae1a47186c03a32177042e55dbc5fd5aee900b8e0069a8d70fba96a9375cd012",
        strip_prefix = "sha1_smol-1.0.0",
        build_file = Label("//remote/remote:BUILD.sha1_smol-1.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha2__0_10_2",
        url = "https://crates.io/api/v1/crates/sha2/0.10.2/download",
        type = "tar.gz",
        sha256 = "55deaec60f81eefe3cce0dc50bda92d6d8e88f2a27df7c5033b42afeb1ed2676",
        strip_prefix = "sha2-0.10.2",
        build_file = Label("//remote/remote:BUILD.sha2-0.10.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sha2__0_8_2",
        url = "https://crates.io/api/v1/crates/sha2/0.8.2/download",
        type = "tar.gz",
        sha256 = "a256f46ea78a0c0d9ff00077504903ac881a1dafdc20da66545699e7776b3e69",
        strip_prefix = "sha2-0.8.2",
        build_file = Label("//remote/remote:BUILD.sha2-0.8.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__shellexpand__2_1_0",
        url = "https://crates.io/api/v1/crates/shellexpand/2.1.0/download",
        type = "tar.gz",
        sha256 = "83bdb7831b2d85ddf4a7b148aa19d0587eddbe8671a436b7bd1182eaad0f2829",
        strip_prefix = "shellexpand-2.1.0",
        build_file = Label("//remote/remote:BUILD.shellexpand-2.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__signal_hook_registry__1_4_0",
        url = "https://crates.io/api/v1/crates/signal-hook-registry/1.4.0/download",
        type = "tar.gz",
        sha256 = "e51e73328dc4ac0c7ccbda3a494dfa03df1de2f46018127f60c693f2648455b0",
        strip_prefix = "signal-hook-registry-1.4.0",
        build_file = Label("//remote/remote:BUILD.signal-hook-registry-1.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__siphasher__0_3_10",
        url = "https://crates.io/api/v1/crates/siphasher/0.3.10/download",
        type = "tar.gz",
        sha256 = "7bd3e3206899af3f8b12af284fafc038cc1dc2b41d1b89dd17297221c5d225de",
        strip_prefix = "siphasher-0.3.10",
        build_file = Label("//remote/remote:BUILD.siphasher-0.3.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__slab__0_4_7",
        url = "https://crates.io/api/v1/crates/slab/0.4.7/download",
        type = "tar.gz",
        sha256 = "4614a76b2a8be0058caa9dbbaf66d988527d86d003c11a94fbd335d7661edcef",
        strip_prefix = "slab-0.4.7",
        build_file = Label("//remote/remote:BUILD.slab-0.4.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__smallvec__1_9_0",
        url = "https://crates.io/api/v1/crates/smallvec/1.9.0/download",
        type = "tar.gz",
        sha256 = "2fd0db749597d91ff862fd1d55ea87f7855a744a8425a64695b6fca237d1dad1",
        strip_prefix = "smallvec-1.9.0",
        build_file = Label("//remote/remote:BUILD.smallvec-1.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__socket2__0_4_4",
        url = "https://crates.io/api/v1/crates/socket2/0.4.4/download",
        type = "tar.gz",
        sha256 = "66d72b759436ae32898a2af0a14218dbf55efde3feeb170eb623637db85ee1e0",
        strip_prefix = "socket2-0.4.4",
        build_file = Label("//remote/remote:BUILD.socket2-0.4.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia/0.7.2/download",
        type = "tar.gz",
        sha256 = "044d2d79633c0413a3cdb5b3cdd6f18b2d6a7f0d76cb75d3251ff92a83c4f55d",
        strip_prefix = "sophia-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_api__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_api/0.7.2/download",
        type = "tar.gz",
        sha256 = "aad03aad8253bd0f7c5423da4a1aaf4b18e5856b40e8841063ba5226cebc5efb",
        strip_prefix = "sophia_api-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_api-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_indexed__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_indexed/0.7.2/download",
        type = "tar.gz",
        sha256 = "f8385acd3ff5e36a22fe4f6d308a10a66b87bbb437bcab096c1d88d522b05ece",
        strip_prefix = "sophia_indexed-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_indexed-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_inmem__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_inmem/0.7.2/download",
        type = "tar.gz",
        sha256 = "28f09086332b823c4d8fa2365987cf881f1c6a9b139991db78c09729a5a3442c",
        strip_prefix = "sophia_inmem-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_inmem-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_iri__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_iri/0.7.2/download",
        type = "tar.gz",
        sha256 = "ecf2b1953a03e53c8cbfb029646be5b75c7e3a83cde8ef16ffe185c471093437",
        strip_prefix = "sophia_iri-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_iri-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_rio__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_rio/0.7.2/download",
        type = "tar.gz",
        sha256 = "fbdcd2f32812619d11e0c531ce35f6d2704fa354dec97ca4072872744d042311",
        strip_prefix = "sophia_rio-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_rio-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_term__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_term/0.7.2/download",
        type = "tar.gz",
        sha256 = "9d21426110f6c45ba6f6a0f5354b4d201cc42a00d2550f7c7ca26e6d6ba89490",
        strip_prefix = "sophia_term-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_term-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__sophia_turtle__0_7_2",
        url = "https://crates.io/api/v1/crates/sophia_turtle/0.7.2/download",
        type = "tar.gz",
        sha256 = "d31f4522a1fb3a49144c20f3cce6a00e1d6c33b5552c0338311868cbb62c7f5d",
        strip_prefix = "sophia_turtle-0.7.2",
        build_file = Label("//remote/remote:BUILD.sophia_turtle-0.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__spin__0_5_2",
        url = "https://crates.io/api/v1/crates/spin/0.5.2/download",
        type = "tar.gz",
        sha256 = "6e63cff320ae2c57904679ba7cb63280a3dc4613885beafb148ee7bf9aa9042d",
        strip_prefix = "spin-0.5.2",
        build_file = Label("//remote/remote:BUILD.spin-0.5.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__stable_deref_trait__1_2_0",
        url = "https://crates.io/api/v1/crates/stable_deref_trait/1.2.0/download",
        type = "tar.gz",
        sha256 = "a8f112729512f8e442d81f95a8a7ddf2b7c6b8a1a6f509a95864142b30cab2d3",
        strip_prefix = "stable_deref_trait-1.2.0",
        build_file = Label("//remote/remote:BUILD.stable_deref_trait-1.2.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__string_cache__0_8_4",
        url = "https://crates.io/api/v1/crates/string_cache/0.8.4/download",
        type = "tar.gz",
        sha256 = "213494b7a2b503146286049378ce02b482200519accc31872ee8be91fa820a08",
        strip_prefix = "string_cache-0.8.4",
        build_file = Label("//remote/remote:BUILD.string_cache-0.8.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__string_cache_codegen__0_5_2",
        url = "https://crates.io/api/v1/crates/string_cache_codegen/0.5.2/download",
        type = "tar.gz",
        sha256 = "6bb30289b722be4ff74a408c3cc27edeaad656e06cb1fe8fa9231fa59c728988",
        strip_prefix = "string_cache_codegen-0.5.2",
        build_file = Label("//remote/remote:BUILD.string_cache_codegen-0.5.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__strsim__0_10_0",
        url = "https://crates.io/api/v1/crates/strsim/0.10.0/download",
        type = "tar.gz",
        sha256 = "73473c0e59e6d5812c5dfe2a064a6444949f089e20eec9a2e5506596494e4623",
        strip_prefix = "strsim-0.10.0",
        build_file = Label("//remote/remote:BUILD.strsim-0.10.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__strsim__0_7_0",
        url = "https://crates.io/api/v1/crates/strsim/0.7.0/download",
        type = "tar.gz",
        sha256 = "bb4f380125926a99e52bc279241539c018323fab05ad6368b56f93d9369ff550",
        strip_prefix = "strsim-0.7.0",
        build_file = Label("//remote/remote:BUILD.strsim-0.7.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__strsim__0_8_0",
        url = "https://crates.io/api/v1/crates/strsim/0.8.0/download",
        type = "tar.gz",
        sha256 = "8ea5119cdb4c55b55d432abb513a0429384878c15dde60cc77b1c99de1a95a6a",
        strip_prefix = "strsim-0.8.0",
        build_file = Label("//remote/remote:BUILD.strsim-0.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__structopt__0_3_26",
        url = "https://crates.io/api/v1/crates/structopt/0.3.26/download",
        type = "tar.gz",
        sha256 = "0c6b5c64445ba8094a6ab0c3cd2ad323e07171012d9c98b0b15651daf1787a10",
        strip_prefix = "structopt-0.3.26",
        build_file = Label("//remote/remote:BUILD.structopt-0.3.26.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__structopt_derive__0_4_18",
        url = "https://crates.io/api/v1/crates/structopt-derive/0.4.18/download",
        type = "tar.gz",
        sha256 = "dcb5ae327f9cc13b68763b5749770cb9e048a99bd9dfdfa58d0cf05d5f64afe0",
        strip_prefix = "structopt-derive-0.4.18",
        build_file = Label("//remote/remote:BUILD.structopt-derive-0.4.18.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__subtle__1_0_0",
        url = "https://crates.io/api/v1/crates/subtle/1.0.0/download",
        type = "tar.gz",
        sha256 = "2d67a5a62ba6e01cb2192ff309324cb4875d0c451d55fe2319433abe7a05a8ee",
        strip_prefix = "subtle-1.0.0",
        build_file = Label("//remote/remote:BUILD.subtle-1.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__subtle__2_4_1",
        url = "https://crates.io/api/v1/crates/subtle/2.4.1/download",
        type = "tar.gz",
        sha256 = "6bdef32e8150c2a081110b42772ffe7d7c9032b606bc226c8260fd97e0976601",
        strip_prefix = "subtle-2.4.1",
        build_file = Label("//remote/remote:BUILD.subtle-2.4.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__syn__0_15_44",
        url = "https://crates.io/api/v1/crates/syn/0.15.44/download",
        type = "tar.gz",
        sha256 = "9ca4b3b69a77cbe1ffc9e198781b7acb0c7365a883670e8f1c1bc66fba79a5c5",
        strip_prefix = "syn-0.15.44",
        build_file = Label("//remote/remote:BUILD.syn-0.15.44.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__syn__1_0_98",
        url = "https://crates.io/api/v1/crates/syn/1.0.98/download",
        type = "tar.gz",
        sha256 = "c50aef8a904de4c23c788f104b7dddc7d6f79c647c7c8ce4cc8f73eb0ca773dd",
        strip_prefix = "syn-1.0.98",
        build_file = Label("//remote/remote:BUILD.syn-1.0.98.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__synstructure__0_12_6",
        url = "https://crates.io/api/v1/crates/synstructure/0.12.6/download",
        type = "tar.gz",
        sha256 = "f36bdaa60a83aca3921b5259d5400cbf5e90fc51931376a9bd4a0eb79aa7210f",
        strip_prefix = "synstructure-0.12.6",
        build_file = Label("//remote/remote:BUILD.synstructure-0.12.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tempfile__3_3_0",
        url = "https://crates.io/api/v1/crates/tempfile/3.3.0/download",
        type = "tar.gz",
        sha256 = "5cdb1ef4eaeeaddc8fbd371e5017057064af0911902ef36b39801f67cc6d79e4",
        strip_prefix = "tempfile-3.3.0",
        build_file = Label("//remote/remote:BUILD.tempfile-3.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tendril__0_4_3",
        url = "https://crates.io/api/v1/crates/tendril/0.4.3/download",
        type = "tar.gz",
        sha256 = "d24a120c5fc464a3458240ee02c299ebcb9d67b5249c8848b09d639dca8d7bb0",
        strip_prefix = "tendril-0.4.3",
        build_file = Label("//remote/remote:BUILD.tendril-0.4.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__term_table__1_3_2",
        url = "https://crates.io/api/v1/crates/term-table/1.3.2/download",
        type = "tar.gz",
        sha256 = "d5e59d7fb313157de2a568be8d81e4d7f9af6e50e697702e8e00190a6566d3b8",
        strip_prefix = "term-table-1.3.2",
        build_file = Label("//remote/remote:BUILD.term-table-1.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__termcolor__1_1_3",
        url = "https://crates.io/api/v1/crates/termcolor/1.1.3/download",
        type = "tar.gz",
        sha256 = "bab24d30b911b2376f3a13cc2cd443142f0c81dda04c118693e35b3835757755",
        strip_prefix = "termcolor-1.1.3",
        build_file = Label("//remote/remote:BUILD.termcolor-1.1.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__textwrap__0_11_0",
        url = "https://crates.io/api/v1/crates/textwrap/0.11.0/download",
        type = "tar.gz",
        sha256 = "d326610f408c7a4eb6f51c37c330e496b08506c9457c9d34287ecc38809fb060",
        strip_prefix = "textwrap-0.11.0",
        build_file = Label("//remote/remote:BUILD.textwrap-0.11.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thin_slice__0_1_1",
        url = "https://crates.io/api/v1/crates/thin-slice/0.1.1/download",
        type = "tar.gz",
        sha256 = "8eaa81235c7058867fa8c0e7314f33dcce9c215f535d1913822a2b3f5e289f3c",
        strip_prefix = "thin-slice-0.1.1",
        build_file = Label("//remote/remote:BUILD.thin-slice-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thiserror__1_0_31",
        url = "https://crates.io/api/v1/crates/thiserror/1.0.31/download",
        type = "tar.gz",
        sha256 = "bd829fe32373d27f76265620b5309d0340cb8550f523c1dda251d6298069069a",
        strip_prefix = "thiserror-1.0.31",
        build_file = Label("//remote/remote:BUILD.thiserror-1.0.31.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thiserror_impl__1_0_31",
        url = "https://crates.io/api/v1/crates/thiserror-impl/1.0.31/download",
        type = "tar.gz",
        sha256 = "0396bc89e626244658bef819e22d0cc459e795a5ebe878e6ec336d1674a8d79a",
        strip_prefix = "thiserror-impl-1.0.31",
        build_file = Label("//remote/remote:BUILD.thiserror-impl-1.0.31.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thread_id__2_0_0",
        url = "https://crates.io/api/v1/crates/thread-id/2.0.0/download",
        type = "tar.gz",
        sha256 = "a9539db560102d1cef46b8b78ce737ff0bb64e7e18d35b2a5688f7d097d0ff03",
        strip_prefix = "thread-id-2.0.0",
        build_file = Label("//remote/remote:BUILD.thread-id-2.0.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thread_local__0_2_7",
        url = "https://crates.io/api/v1/crates/thread_local/0.2.7/download",
        type = "tar.gz",
        sha256 = "8576dbbfcaef9641452d5cf0df9b0e7eeab7694956dd33bb61515fb8f18cfdd5",
        strip_prefix = "thread_local-0.2.7",
        build_file = Label("//remote/remote:BUILD.thread_local-0.2.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__thread_local__0_3_6",
        url = "https://crates.io/api/v1/crates/thread_local/0.3.6/download",
        type = "tar.gz",
        sha256 = "c6b53e329000edc2b34dbe8545fd20e55a333362d0a321909685a19bd28c3f1b",
        strip_prefix = "thread_local-0.3.6",
        build_file = Label("//remote/remote:BUILD.thread_local-0.3.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__time__0_1_44",
        url = "https://crates.io/api/v1/crates/time/0.1.44/download",
        type = "tar.gz",
        sha256 = "6db9e6914ab8b1ae1c260a4ae7a49b6c5611b40328a735b21862567685e73255",
        strip_prefix = "time-0.1.44",
        build_file = Label("//remote/remote:BUILD.time-0.1.44.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tinyvec__1_6_0",
        url = "https://crates.io/api/v1/crates/tinyvec/1.6.0/download",
        type = "tar.gz",
        sha256 = "87cc5ceb3875bb20c2890005a4e226a4651264a5c75edb2421b52861a0a0cb50",
        strip_prefix = "tinyvec-1.6.0",
        build_file = Label("//remote/remote:BUILD.tinyvec-1.6.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tinyvec_macros__0_1_0",
        url = "https://crates.io/api/v1/crates/tinyvec_macros/0.1.0/download",
        type = "tar.gz",
        sha256 = "cda74da7e1a664f795bb1f8a87ec406fb89a02522cf6e50620d016add6dbbf5c",
        strip_prefix = "tinyvec_macros-0.1.0",
        build_file = Label("//remote/remote:BUILD.tinyvec_macros-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio__1_20_1",
        url = "https://crates.io/api/v1/crates/tokio/1.20.1/download",
        type = "tar.gz",
        sha256 = "7a8325f63a7d4774dd041e363b2409ed1c5cbbd0f867795e661df066b2b0a581",
        strip_prefix = "tokio-1.20.1",
        build_file = Label("//remote/remote:BUILD.tokio-1.20.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_macros__1_8_0",
        url = "https://crates.io/api/v1/crates/tokio-macros/1.8.0/download",
        type = "tar.gz",
        sha256 = "9724f9a975fb987ef7a3cd9be0350edcbe130698af5b8f7a631e23d42d052484",
        strip_prefix = "tokio-macros-1.8.0",
        build_file = Label("//remote/remote:BUILD.tokio-macros-1.8.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_native_tls__0_3_0",
        url = "https://crates.io/api/v1/crates/tokio-native-tls/0.3.0/download",
        type = "tar.gz",
        sha256 = "f7d995660bd2b7f8c1568414c1126076c13fbb725c40112dc0120b78eb9b717b",
        strip_prefix = "tokio-native-tls-0.3.0",
        build_file = Label("//remote/remote:BUILD.tokio-native-tls-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_rustls__0_23_4",
        url = "https://crates.io/api/v1/crates/tokio-rustls/0.23.4/download",
        type = "tar.gz",
        sha256 = "c43ee83903113e03984cb9e5cebe6c04a5116269e900e3ddba8f068a62adda59",
        strip_prefix = "tokio-rustls-0.23.4",
        build_file = Label("//remote/remote:BUILD.tokio-rustls-0.23.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_stream__0_1_9",
        url = "https://crates.io/api/v1/crates/tokio-stream/0.1.9/download",
        type = "tar.gz",
        sha256 = "df54d54117d6fdc4e4fea40fe1e4e566b3505700e148a6827e59b34b0d2600d9",
        strip_prefix = "tokio-stream-0.1.9",
        build_file = Label("//remote/remote:BUILD.tokio-stream-0.1.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_tungstenite__0_14_0",
        url = "https://crates.io/api/v1/crates/tokio-tungstenite/0.14.0/download",
        type = "tar.gz",
        sha256 = "1e96bb520beab540ab664bd5a9cfeaa1fcd846fa68c830b42e2c8963071251d2",
        strip_prefix = "tokio-tungstenite-0.14.0",
        build_file = Label("//remote/remote:BUILD.tokio-tungstenite-0.14.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_tungstenite__0_15_0",
        url = "https://crates.io/api/v1/crates/tokio-tungstenite/0.15.0/download",
        type = "tar.gz",
        sha256 = "511de3f85caf1c98983545490c3d09685fa8eb634e57eec22bb4db271f46cbd8",
        strip_prefix = "tokio-tungstenite-0.15.0",
        build_file = Label("//remote/remote:BUILD.tokio-tungstenite-0.15.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_util__0_6_10",
        url = "https://crates.io/api/v1/crates/tokio-util/0.6.10/download",
        type = "tar.gz",
        sha256 = "36943ee01a6d67977dd3f84a5a1d2efeb4ada3a1ae771cadfaa535d9d9fc6507",
        strip_prefix = "tokio-util-0.6.10",
        build_file = Label("//remote/remote:BUILD.tokio-util-0.6.10.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_util__0_7_3",
        url = "https://crates.io/api/v1/crates/tokio-util/0.7.3/download",
        type = "tar.gz",
        sha256 = "cc463cd8deddc3770d20f9852143d50bf6094e640b485cb2e189a2099085ff45",
        strip_prefix = "tokio-util-0.7.3",
        build_file = Label("//remote/remote:BUILD.tokio-util-0.7.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__toml__0_5_9",
        url = "https://crates.io/api/v1/crates/toml/0.5.9/download",
        type = "tar.gz",
        sha256 = "8d82e1a7758622a465f8cee077614c73484dac5b836c02ff6a40d5d1010324d7",
        strip_prefix = "toml-0.5.9",
        build_file = Label("//remote/remote:BUILD.toml-0.5.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tower_service__0_3_2",
        url = "https://crates.io/api/v1/crates/tower-service/0.3.2/download",
        type = "tar.gz",
        sha256 = "b6bc1c9ce2b5135ac7f93c72918fc37feb872bdc6a5533a8b85eb4b86bfdae52",
        strip_prefix = "tower-service-0.3.2",
        build_file = Label("//remote/remote:BUILD.tower-service-0.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tracing__0_1_35",
        url = "https://crates.io/api/v1/crates/tracing/0.1.35/download",
        type = "tar.gz",
        sha256 = "a400e31aa60b9d44a52a8ee0343b5b18566b03a8321e0d321f695cf56e940160",
        strip_prefix = "tracing-0.1.35",
        build_file = Label("//remote/remote:BUILD.tracing-0.1.35.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tracing_core__0_1_28",
        url = "https://crates.io/api/v1/crates/tracing-core/0.1.28/download",
        type = "tar.gz",
        sha256 = "7b7358be39f2f274f322d2aaed611acc57f382e8eb1e5b48cb9ae30933495ce7",
        strip_prefix = "tracing-core-0.1.28",
        build_file = Label("//remote/remote:BUILD.tracing-core-0.1.28.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__traitobject__0_1_0",
        url = "https://crates.io/api/v1/crates/traitobject/0.1.0/download",
        type = "tar.gz",
        sha256 = "efd1f82c56340fdf16f2a953d7bda4f8fdffba13d93b00844c25572110b26079",
        strip_prefix = "traitobject-0.1.0",
        build_file = Label("//remote/remote:BUILD.traitobject-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__try_lock__0_2_3",
        url = "https://crates.io/api/v1/crates/try-lock/0.2.3/download",
        type = "tar.gz",
        sha256 = "59547bce71d9c38b83d9c0e92b6066c4253371f15005def0c30d9657f50c7642",
        strip_prefix = "try-lock-0.2.3",
        build_file = Label("//remote/remote:BUILD.try-lock-0.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tungstenite__0_13_0",
        url = "https://crates.io/api/v1/crates/tungstenite/0.13.0/download",
        type = "tar.gz",
        sha256 = "5fe8dada8c1a3aeca77d6b51a4f1314e0f4b8e438b7b1b71e3ddaca8080e4093",
        strip_prefix = "tungstenite-0.13.0",
        build_file = Label("//remote/remote:BUILD.tungstenite-0.13.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tungstenite__0_14_0",
        url = "https://crates.io/api/v1/crates/tungstenite/0.14.0/download",
        type = "tar.gz",
        sha256 = "a0b2d8558abd2e276b0a8df5c05a2ec762609344191e5fd23e292c910e9165b5",
        strip_prefix = "tungstenite-0.14.0",
        build_file = Label("//remote/remote:BUILD.tungstenite-0.14.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__twoway__0_1_8",
        url = "https://crates.io/api/v1/crates/twoway/0.1.8/download",
        type = "tar.gz",
        sha256 = "59b11b2b5241ba34be09c3cc85a36e56e48f9888862e19cedf23336d35316ed1",
        strip_prefix = "twoway-0.1.8",
        build_file = Label("//remote/remote:BUILD.twoway-0.1.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__typeable__0_1_2",
        url = "https://crates.io/api/v1/crates/typeable/0.1.2/download",
        type = "tar.gz",
        sha256 = "1410f6f91f21d1612654e7cc69193b0334f909dcf2c790c4826254fbb86f8887",
        strip_prefix = "typeable-0.1.2",
        build_file = Label("//remote/remote:BUILD.typeable-0.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__typenum__1_15_0",
        url = "https://crates.io/api/v1/crates/typenum/1.15.0/download",
        type = "tar.gz",
        sha256 = "dcf81ac59edc17cc8697ff311e8f5ef2d99fcbd9817b34cec66f90b6c3dfd987",
        strip_prefix = "typenum-1.15.0",
        build_file = Label("//remote/remote:BUILD.typenum-1.15.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__ucd_util__0_1_9",
        url = "https://crates.io/api/v1/crates/ucd-util/0.1.9/download",
        type = "tar.gz",
        sha256 = "65bfcbf611b122f2c10eb1bb6172fbc4c2e25df9970330e4d75ce2b5201c9bfc",
        strip_prefix = "ucd-util-0.1.9",
        build_file = Label("//remote/remote:BUILD.ucd-util-0.1.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__uncased__0_9_7",
        url = "https://crates.io/api/v1/crates/uncased/0.9.7/download",
        type = "tar.gz",
        sha256 = "09b01702b0fd0b3fadcf98e098780badda8742d4f4a7676615cad90e8ac73622",
        strip_prefix = "uncased-0.9.7",
        build_file = Label("//remote/remote:BUILD.uncased-0.9.7.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicase__1_4_2",
        url = "https://crates.io/api/v1/crates/unicase/1.4.2/download",
        type = "tar.gz",
        sha256 = "7f4765f83163b74f957c797ad9253caf97f103fb064d3999aea9568d09fc8a33",
        strip_prefix = "unicase-1.4.2",
        build_file = Label("//remote/remote:BUILD.unicase-1.4.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicase__2_6_0",
        url = "https://crates.io/api/v1/crates/unicase/2.6.0/download",
        type = "tar.gz",
        sha256 = "50f37be617794602aabbeee0be4f259dc1778fabe05e2d67ee8f79326d5cb4f6",
        strip_prefix = "unicase-2.6.0",
        build_file = Label("//remote/remote:BUILD.unicase-2.6.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_bidi__0_3_8",
        url = "https://crates.io/api/v1/crates/unicode-bidi/0.3.8/download",
        type = "tar.gz",
        sha256 = "099b7128301d285f79ddd55b9a83d5e6b9e97c92e0ea0daebee7263e932de992",
        strip_prefix = "unicode-bidi-0.3.8",
        build_file = Label("//remote/remote:BUILD.unicode-bidi-0.3.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_ident__1_0_2",
        url = "https://crates.io/api/v1/crates/unicode-ident/1.0.2/download",
        type = "tar.gz",
        sha256 = "15c61ba63f9235225a22310255a29b806b907c9b8c964bcbd0a2c70f3f2deea7",
        strip_prefix = "unicode-ident-1.0.2",
        build_file = Label("//remote/remote:BUILD.unicode-ident-1.0.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_normalization__0_1_21",
        url = "https://crates.io/api/v1/crates/unicode-normalization/0.1.21/download",
        type = "tar.gz",
        sha256 = "854cbdc4f7bc6ae19c820d44abdc3277ac3e1b2b93db20a636825d9322fb60e6",
        strip_prefix = "unicode-normalization-0.1.21",
        build_file = Label("//remote/remote:BUILD.unicode-normalization-0.1.21.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_segmentation__1_9_0",
        url = "https://crates.io/api/v1/crates/unicode-segmentation/1.9.0/download",
        type = "tar.gz",
        sha256 = "7e8820f5d777f6224dc4be3632222971ac30164d4a258d595640799554ebfd99",
        strip_prefix = "unicode-segmentation-1.9.0",
        build_file = Label("//remote/remote:BUILD.unicode-segmentation-1.9.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_width__0_1_9",
        url = "https://crates.io/api/v1/crates/unicode-width/0.1.9/download",
        type = "tar.gz",
        sha256 = "3ed742d4ea2bd1176e236172c8429aaf54486e7ac098db29ffe6529e0ce50973",
        strip_prefix = "unicode-width-0.1.9",
        build_file = Label("//remote/remote:BUILD.unicode-width-0.1.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_xid__0_1_0",
        url = "https://crates.io/api/v1/crates/unicode-xid/0.1.0/download",
        type = "tar.gz",
        sha256 = "fc72304796d0818e357ead4e000d19c9c174ab23dc11093ac919054d20a6a7fc",
        strip_prefix = "unicode-xid-0.1.0",
        build_file = Label("//remote/remote:BUILD.unicode-xid-0.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_xid__0_2_3",
        url = "https://crates.io/api/v1/crates/unicode-xid/0.2.3/download",
        type = "tar.gz",
        sha256 = "957e51f3646910546462e67d5f7599b9e4fb8acdd304b087a6494730f9eebf04",
        strip_prefix = "unicode-xid-0.2.3",
        build_file = Label("//remote/remote:BUILD.unicode-xid-0.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__untrusted__0_7_1",
        url = "https://crates.io/api/v1/crates/untrusted/0.7.1/download",
        type = "tar.gz",
        sha256 = "a156c684c91ea7d62626509bce3cb4e1d9ed5c4d978f7b4352658f96a4c26b4a",
        strip_prefix = "untrusted-0.7.1",
        build_file = Label("//remote/remote:BUILD.untrusted-0.7.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__uritemplate__0_1_2",
        url = "https://crates.io/api/v1/crates/uritemplate/0.1.2/download",
        type = "tar.gz",
        sha256 = "01eaa32c7380d40c2fd400fb0a95e394b6c40632ca4bcb4bc1683f0fbbf22749",
        strip_prefix = "uritemplate-0.1.2",
        build_file = Label("//remote/remote:BUILD.uritemplate-0.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__url__1_7_2",
        url = "https://crates.io/api/v1/crates/url/1.7.2/download",
        type = "tar.gz",
        sha256 = "dd4e7c0d531266369519a4aa4f399d748bd37043b00bde1e4ff1f60a120b355a",
        strip_prefix = "url-1.7.2",
        build_file = Label("//remote/remote:BUILD.url-1.7.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__url__2_2_2",
        url = "https://crates.io/api/v1/crates/url/2.2.2/download",
        type = "tar.gz",
        sha256 = "a507c383b2d33b5fc35d1861e77e6b383d158b2da5e14fe51b83dfedf6fd578c",
        strip_prefix = "url-2.2.2",
        build_file = Label("//remote/remote:BUILD.url-2.2.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__utf_8__0_7_6",
        url = "https://crates.io/api/v1/crates/utf-8/0.7.6/download",
        type = "tar.gz",
        sha256 = "09cc8ee72d2a9becf2f2febe0205bbed8fc6615b7cb429ad062dc7b7ddd036a9",
        strip_prefix = "utf-8-0.7.6",
        build_file = Label("//remote/remote:BUILD.utf-8-0.7.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__utf8_ranges__0_1_3",
        url = "https://crates.io/api/v1/crates/utf8-ranges/0.1.3/download",
        type = "tar.gz",
        sha256 = "a1ca13c08c41c9c3e04224ed9ff80461d97e121589ff27c753a16cb10830ae0f",
        strip_prefix = "utf8-ranges-0.1.3",
        build_file = Label("//remote/remote:BUILD.utf8-ranges-0.1.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__utf8_ranges__1_0_5",
        url = "https://crates.io/api/v1/crates/utf8-ranges/1.0.5/download",
        type = "tar.gz",
        sha256 = "7fcfc827f90e53a02eaef5e535ee14266c1d569214c6aa70133a624d8a3164ba",
        strip_prefix = "utf8-ranges-1.0.5",
        build_file = Label("//remote/remote:BUILD.utf8-ranges-1.0.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__uuid__1_1_2",
        url = "https://crates.io/api/v1/crates/uuid/1.1.2/download",
        type = "tar.gz",
        sha256 = "dd6469f4314d5f1ffec476e05f17cc9a78bc7a27a6a857842170bdf8d6f98d2f",
        strip_prefix = "uuid-1.1.2",
        build_file = Label("//remote/remote:BUILD.uuid-1.1.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__vcpkg__0_2_15",
        url = "https://crates.io/api/v1/crates/vcpkg/0.2.15/download",
        type = "tar.gz",
        sha256 = "accd4ea62f7bb7a82fe23066fb0957d48ef677f6eeb8215f372f52e48bb32426",
        strip_prefix = "vcpkg-0.2.15",
        build_file = Label("//remote/remote:BUILD.vcpkg-0.2.15.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__vec_map__0_8_2",
        url = "https://crates.io/api/v1/crates/vec_map/0.8.2/download",
        type = "tar.gz",
        sha256 = "f1bddf1187be692e79c5ffeab891132dfb0f236ed36a43c7ed39f1165ee20191",
        strip_prefix = "vec_map-0.8.2",
        build_file = Label("//remote/remote:BUILD.vec_map-0.8.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__version_check__0_1_5",
        url = "https://crates.io/api/v1/crates/version_check/0.1.5/download",
        type = "tar.gz",
        sha256 = "914b1a6776c4c929a602fafd8bc742e06365d4bcbe48c30f9cca5824f70dc9dd",
        strip_prefix = "version_check-0.1.5",
        build_file = Label("//remote/remote:BUILD.version_check-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__version_check__0_9_4",
        url = "https://crates.io/api/v1/crates/version_check/0.9.4/download",
        type = "tar.gz",
        sha256 = "49874b5167b65d7193b8aba1567f5c7d93d001cafc34600cee003eda787e483f",
        strip_prefix = "version_check-0.9.4",
        build_file = Label("//remote/remote:BUILD.version_check-0.9.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__want__0_3_0",
        url = "https://crates.io/api/v1/crates/want/0.3.0/download",
        type = "tar.gz",
        sha256 = "1ce8a968cb1cd110d136ff8b819a556d6fb6d919363c61534f6860c7eb172ba0",
        strip_prefix = "want-0.3.0",
        build_file = Label("//remote/remote:BUILD.want-0.3.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__warp__0_3_2",
        url = "https://crates.io/api/v1/crates/warp/0.3.2/download",
        type = "tar.gz",
        sha256 = "3cef4e1e9114a4b7f1ac799f16ce71c14de5778500c5450ec6b7b920c55b587e",
        strip_prefix = "warp-0.3.2",
        build_file = Label("//remote/remote:BUILD.warp-0.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasi__0_10_0_wasi_snapshot_preview1",
        url = "https://crates.io/api/v1/crates/wasi/0.10.0+wasi-snapshot-preview1/download",
        type = "tar.gz",
        sha256 = "1a143597ca7c7793eff794def352d41792a93c481eb1042423ff7ff72ba2c31f",
        strip_prefix = "wasi-0.10.0+wasi-snapshot-preview1",
        build_file = Label("//remote/remote:BUILD.wasi-0.10.0+wasi-snapshot-preview1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasi__0_11_0_wasi_snapshot_preview1",
        url = "https://crates.io/api/v1/crates/wasi/0.11.0+wasi-snapshot-preview1/download",
        type = "tar.gz",
        sha256 = "9c8d87e72b64a3b4db28d11ce29237c246188f4f51057d65a7eab63b7987e423",
        strip_prefix = "wasi-0.11.0+wasi-snapshot-preview1",
        build_file = Label("//remote/remote:BUILD.wasi-0.11.0+wasi-snapshot-preview1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasi__0_9_0_wasi_snapshot_preview1",
        url = "https://crates.io/api/v1/crates/wasi/0.9.0+wasi-snapshot-preview1/download",
        type = "tar.gz",
        sha256 = "cccddf32554fecc6acb585f82a32a72e28b48f8c4c1883ddfeeeaa96f7d8e519",
        strip_prefix = "wasi-0.9.0+wasi-snapshot-preview1",
        build_file = Label("//remote/remote:BUILD.wasi-0.9.0+wasi-snapshot-preview1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen__0_2_82",
        url = "https://crates.io/api/v1/crates/wasm-bindgen/0.2.82/download",
        type = "tar.gz",
        sha256 = "fc7652e3f6c4706c8d9cd54832c4a4ccb9b5336e2c3bd154d5cccfbf1c1f5f7d",
        strip_prefix = "wasm-bindgen-0.2.82",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-0.2.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_backend__0_2_82",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-backend/0.2.82/download",
        type = "tar.gz",
        sha256 = "662cd44805586bd52971b9586b1df85cdbbd9112e4ef4d8f41559c334dc6ac3f",
        strip_prefix = "wasm-bindgen-backend-0.2.82",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-backend-0.2.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_futures__0_4_32",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-futures/0.4.32/download",
        type = "tar.gz",
        sha256 = "fa76fb221a1f8acddf5b54ace85912606980ad661ac7a503b4570ffd3a624dad",
        strip_prefix = "wasm-bindgen-futures-0.4.32",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-futures-0.4.32.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_macro__0_2_82",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-macro/0.2.82/download",
        type = "tar.gz",
        sha256 = "b260f13d3012071dfb1512849c033b1925038373aea48ced3012c09df952c602",
        strip_prefix = "wasm-bindgen-macro-0.2.82",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-macro-0.2.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_macro_support__0_2_82",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-macro-support/0.2.82/download",
        type = "tar.gz",
        sha256 = "5be8e654bdd9b79216c2929ab90721aa82faf65c48cdf08bdc4e7f51357b80da",
        strip_prefix = "wasm-bindgen-macro-support-0.2.82",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-macro-support-0.2.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_shared__0_2_82",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-shared/0.2.82/download",
        type = "tar.gz",
        sha256 = "6598dd0bd3c7d51095ff6531a5b23e02acdc81804e30d8f07afb77b7215a140a",
        strip_prefix = "wasm-bindgen-shared-0.2.82",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-shared-0.2.82.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__weak_table__0_3_2",
        url = "https://crates.io/api/v1/crates/weak-table/0.3.2/download",
        type = "tar.gz",
        sha256 = "323f4da9523e9a669e1eaf9c6e763892769b1d38c623913647bfdc1532fe4549",
        strip_prefix = "weak-table-0.3.2",
        build_file = Label("//remote/remote:BUILD.weak-table-0.3.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__web_sys__0_3_59",
        url = "https://crates.io/api/v1/crates/web-sys/0.3.59/download",
        type = "tar.gz",
        sha256 = "ed055ab27f941423197eb86b2035720b1a3ce40504df082cac2ecc6ed73335a1",
        strip_prefix = "web-sys-0.3.59",
        build_file = Label("//remote/remote:BUILD.web-sys-0.3.59.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__webpki__0_22_0",
        url = "https://crates.io/api/v1/crates/webpki/0.22.0/download",
        type = "tar.gz",
        sha256 = "f095d78192e208183081cc07bc5515ef55216397af48b873e5edcd72637fa1bd",
        strip_prefix = "webpki-0.22.0",
        build_file = Label("//remote/remote:BUILD.webpki-0.22.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__webpki_roots__0_22_4",
        url = "https://crates.io/api/v1/crates/webpki-roots/0.22.4/download",
        type = "tar.gz",
        sha256 = "f1c760f0d366a6c24a02ed7816e23e691f5d92291f94d15e836006fd11b04daf",
        strip_prefix = "webpki-roots-0.22.4",
        build_file = Label("//remote/remote:BUILD.webpki-roots-0.22.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__websocket__0_23_0",
        url = "https://crates.io/api/v1/crates/websocket/0.23.0/download",
        type = "tar.gz",
        sha256 = "b255b190f412e45000c35be7fe9b48b39a2ac5eb90d093d421694e5dae8b335c",
        strip_prefix = "websocket-0.23.0",
        build_file = Label("//remote/remote:BUILD.websocket-0.23.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__which__2_0_1",
        url = "https://crates.io/api/v1/crates/which/2.0.1/download",
        type = "tar.gz",
        sha256 = "b57acb10231b9493c8472b20cb57317d0679a49e0bdbee44b3b803a6473af164",
        strip_prefix = "which-2.0.1",
        build_file = Label("//remote/remote:BUILD.which-2.0.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi__0_2_8",
        url = "https://crates.io/api/v1/crates/winapi/0.2.8/download",
        type = "tar.gz",
        sha256 = "167dc9d6949a9b857f3451275e911c3f44255842c1f7a76f33c55103a909087a",
        strip_prefix = "winapi-0.2.8",
        build_file = Label("//remote/remote:BUILD.winapi-0.2.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi__0_3_9",
        url = "https://crates.io/api/v1/crates/winapi/0.3.9/download",
        type = "tar.gz",
        sha256 = "5c839a674fcd7a98952e593242ea400abe93992746761e38641405d28b00f419",
        strip_prefix = "winapi-0.3.9",
        build_file = Label("//remote/remote:BUILD.winapi-0.3.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi_build__0_1_1",
        url = "https://crates.io/api/v1/crates/winapi-build/0.1.1/download",
        type = "tar.gz",
        sha256 = "2d315eee3b34aca4797b2da6b13ed88266e6d612562a0c46390af8299fc699bc",
        strip_prefix = "winapi-build-0.1.1",
        build_file = Label("//remote/remote:BUILD.winapi-build-0.1.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi_i686_pc_windows_gnu__0_4_0",
        url = "https://crates.io/api/v1/crates/winapi-i686-pc-windows-gnu/0.4.0/download",
        type = "tar.gz",
        sha256 = "ac3b87c63620426dd9b991e5ce0329eff545bccbbb34f3be09ff6fb6ab51b7b6",
        strip_prefix = "winapi-i686-pc-windows-gnu-0.4.0",
        build_file = Label("//remote/remote:BUILD.winapi-i686-pc-windows-gnu-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi_util__0_1_5",
        url = "https://crates.io/api/v1/crates/winapi-util/0.1.5/download",
        type = "tar.gz",
        sha256 = "70ec6ce85bb158151cae5e5c87f95a8e97d2c0c4b001223f33a334e3ce5de178",
        strip_prefix = "winapi-util-0.1.5",
        build_file = Label("//remote/remote:BUILD.winapi-util-0.1.5.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winapi_x86_64_pc_windows_gnu__0_4_0",
        url = "https://crates.io/api/v1/crates/winapi-x86_64-pc-windows-gnu/0.4.0/download",
        type = "tar.gz",
        sha256 = "712e227841d057c1ee1cd2fb22fa7e5a5461ae8e48fa2ca79ec42cfc1931183f",
        strip_prefix = "winapi-x86_64-pc-windows-gnu-0.4.0",
        build_file = Label("//remote/remote:BUILD.winapi-x86_64-pc-windows-gnu-0.4.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_sys__0_36_1",
        url = "https://crates.io/api/v1/crates/windows-sys/0.36.1/download",
        type = "tar.gz",
        sha256 = "ea04155a16a59f9eab786fe12a4a450e75cdb175f9e0d80da1e17db09f55b8d2",
        strip_prefix = "windows-sys-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows-sys-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_aarch64_msvc__0_36_1",
        url = "https://crates.io/api/v1/crates/windows_aarch64_msvc/0.36.1/download",
        type = "tar.gz",
        sha256 = "9bb8c3fd39ade2d67e9874ac4f3db21f0d710bee00fe7cab16949ec184eeaa47",
        strip_prefix = "windows_aarch64_msvc-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows_aarch64_msvc-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_i686_gnu__0_36_1",
        url = "https://crates.io/api/v1/crates/windows_i686_gnu/0.36.1/download",
        type = "tar.gz",
        sha256 = "180e6ccf01daf4c426b846dfc66db1fc518f074baa793aa7d9b9aaeffad6a3b6",
        strip_prefix = "windows_i686_gnu-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows_i686_gnu-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_i686_msvc__0_36_1",
        url = "https://crates.io/api/v1/crates/windows_i686_msvc/0.36.1/download",
        type = "tar.gz",
        sha256 = "e2e7917148b2812d1eeafaeb22a97e4813dfa60a3f8f78ebe204bcc88f12f024",
        strip_prefix = "windows_i686_msvc-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows_i686_msvc-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_x86_64_gnu__0_36_1",
        url = "https://crates.io/api/v1/crates/windows_x86_64_gnu/0.36.1/download",
        type = "tar.gz",
        sha256 = "4dcd171b8776c41b97521e5da127a2d86ad280114807d0b2ab1e462bc764d9e1",
        strip_prefix = "windows_x86_64_gnu-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows_x86_64_gnu-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__windows_x86_64_msvc__0_36_1",
        url = "https://crates.io/api/v1/crates/windows_x86_64_msvc/0.36.1/download",
        type = "tar.gz",
        sha256 = "c811ca4a8c853ef420abd8592ba53ddbbac90410fab6903b3e79972a631f7680",
        strip_prefix = "windows_x86_64_msvc-0.36.1",
        build_file = Label("//remote/remote:BUILD.windows_x86_64_msvc-0.36.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winreg__0_10_1",
        url = "https://crates.io/api/v1/crates/winreg/0.10.1/download",
        type = "tar.gz",
        sha256 = "80d0f4e272c85def139476380b12f9ac60926689dd2e01d4923222f40580869d",
        strip_prefix = "winreg-0.10.1",
        build_file = Label("//remote/remote:BUILD.winreg-0.10.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__winreg__0_6_2",
        url = "https://crates.io/api/v1/crates/winreg/0.6.2/download",
        type = "tar.gz",
        sha256 = "b2986deb581c4fe11b621998a5e53361efe6b48a151178d0cd9eeffa4dc6acc9",
        strip_prefix = "winreg-0.6.2",
        build_file = Label("//remote/remote:BUILD.winreg-0.6.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__xdg__2_4_1",
        url = "https://crates.io/api/v1/crates/xdg/2.4.1/download",
        type = "tar.gz",
        sha256 = "0c4583db5cbd4c4c0303df2d15af80f0539db703fa1c68802d4cbbd2dd0f88f6",
        strip_prefix = "xdg-2.4.1",
        build_file = Label("//remote/remote:BUILD.xdg-2.4.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__xml_rs__0_8_4",
        url = "https://crates.io/api/v1/crates/xml-rs/0.8.4/download",
        type = "tar.gz",
        sha256 = "d2d7d3948613f75c98fd9328cfdcc45acc4d360655289d0a7d4ec931392200a3",
        strip_prefix = "xml-rs-0.8.4",
        build_file = Label("//remote/remote:BUILD.xml-rs-0.8.4.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__yaml_rust__0_4_5",
        url = "https://crates.io/api/v1/crates/yaml-rust/0.4.5/download",
        type = "tar.gz",
        sha256 = "56c1936c4cc7a1c9ab21a1ebb602eb942ba868cbd44a99cb7cdc5892335e1c85",
        strip_prefix = "yaml-rust-0.4.5",
        build_file = Label("//remote/remote:BUILD.yaml-rust-0.4.5.bazel"),
    )
