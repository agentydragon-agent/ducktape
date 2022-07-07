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
        name = "raze__aho_corasick__0_7_18",
        url = "https://crates.io/api/v1/crates/aho-corasick/0.7.18/download",
        type = "tar.gz",
        sha256 = "1e37cfd5e7657ada45f742d6e99ca5788580b5c529dc78faf11ece6dc702656f",
        strip_prefix = "aho-corasick-0.7.18",
        build_file = Label("//remote/remote:BUILD.aho-corasick-0.7.18.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__arrayvec__0_7_2",
        url = "https://crates.io/api/v1/crates/arrayvec/0.7.2/download",
        type = "tar.gz",
        strip_prefix = "arrayvec-0.7.2",
        build_file = Label("//remote/remote:BUILD.arrayvec-0.7.2.bazel"),
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
        name = "raze__autocfg__1_1_0",
        url = "https://crates.io/api/v1/crates/autocfg/1.1.0/download",
        type = "tar.gz",
        sha256 = "d468802bab17cbc0cc575e9b053f41e72aa36bfa6b7f55e3529ffa43161b97fa",
        strip_prefix = "autocfg-1.1.0",
        build_file = Label("//remote/remote:BUILD.autocfg-1.1.0.bazel"),
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
        name = "raze__bitflags__1_3_2",
        url = "https://crates.io/api/v1/crates/bitflags/1.3.2/download",
        type = "tar.gz",
        sha256 = "bef38d45163c2f1dde094a7dfd33ccf595c92905c8f8f4fdc18d06fb1037718a",
        strip_prefix = "bitflags-1.3.2",
        build_file = Label("//remote/remote:BUILD.bitflags-1.3.2.bazel"),
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
        name = "raze__bytes__1_1_0",
        url = "https://crates.io/api/v1/crates/bytes/1.1.0/download",
        type = "tar.gz",
        sha256 = "c4872d67bab6358e59559027aa3b9157c53d9358c51423c17554809a8858e0f8",
        strip_prefix = "bytes-1.1.0",
        build_file = Label("//remote/remote:BUILD.bytes-1.1.0.bazel"),
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
        name = "raze__encoding_rs__0_8_31",
        url = "https://crates.io/api/v1/crates/encoding_rs/0.8.31/download",
        type = "tar.gz",
        sha256 = "9852635589dc9f9ea1b6fe9f05b50ef208c85c834a562f0c6abb1c475736ec2b",
        strip_prefix = "encoding_rs-0.8.31",
        build_file = Label("//remote/remote:BUILD.encoding_rs-0.8.31.bazel"),
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
        name = "raze__fastrand__1_7_0",
        url = "https://crates.io/api/v1/crates/fastrand/1.7.0/download",
        type = "tar.gz",
        sha256 = "c3fcf0cee53519c866c09b5de1f6c56ff9d647101f81c1964fa632e148896cdf",
        strip_prefix = "fastrand-1.7.0",
        build_file = Label("//remote/remote:BUILD.fastrand-1.7.0.bazel"),
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
        name = "raze__h2__0_3_13",
        url = "https://crates.io/api/v1/crates/h2/0.3.13/download",
        type = "tar.gz",
        sha256 = "37a82c6d637fc9515a4694bbf1cb2457b79d81ce52b3108bdeea58b07dd34a57",
        strip_prefix = "h2-0.3.13",
        build_file = Label("//remote/remote:BUILD.h2-0.3.13.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hashbrown__0_11_2",
        url = "https://crates.io/api/v1/crates/hashbrown/0.11.2/download",
        type = "tar.gz",
        sha256 = "ab5ef0d4909ef3724cc8cce6ccc8572c5c817592e9285f5464f8e86f8bd3726e",
        strip_prefix = "hashbrown-0.11.2",
        build_file = Label("//remote/remote:BUILD.hashbrown-0.11.2.bazel"),
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
        name = "raze__humantime__2_1_0",
        url = "https://crates.io/api/v1/crates/humantime/2.1.0/download",
        type = "tar.gz",
        sha256 = "9a3a5bfb195931eeb336b2a7b4d761daec841b97f947d34394601737a7bba5e4",
        strip_prefix = "humantime-2.1.0",
        build_file = Label("//remote/remote:BUILD.humantime-2.1.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__hyper__0_14_19",
        url = "https://crates.io/api/v1/crates/hyper/0.14.19/download",
        type = "tar.gz",
        sha256 = "42dc3c131584288d375f2d07f822b0cb012d8c6fb899a5b9fdb3cb7eb9b6004f",
        strip_prefix = "hyper-0.14.19",
        build_file = Label("//remote/remote:BUILD.hyper-0.14.19.bazel"),
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
        name = "raze__idna__0_2_3",
        url = "https://crates.io/api/v1/crates/idna/0.2.3/download",
        type = "tar.gz",
        sha256 = "418a0a6fab821475f634efe3ccc45c013f742efe03d853e8d3355d5cb850ecf8",
        strip_prefix = "idna-0.2.3",
        build_file = Label("//remote/remote:BUILD.idna-0.2.3.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__indexmap__1_8_2",
        url = "https://crates.io/api/v1/crates/indexmap/1.8.2/download",
        type = "tar.gz",
        sha256 = "e6012d540c5baa3589337a98ce73408de9b5a25ec9fc2c6fd6be8f0d39e0ca5a",
        strip_prefix = "indexmap-1.8.2",
        build_file = Label("//remote/remote:BUILD.indexmap-1.8.2.bazel"),
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
        name = "raze__itoa__1_0_2",
        url = "https://crates.io/api/v1/crates/itoa/1.0.2/download",
        type = "tar.gz",
        sha256 = "112c678d4050afce233f4f2852bb2eb519230b3cf12f33585275537d7e41578d",
        strip_prefix = "itoa-1.0.2",
        build_file = Label("//remote/remote:BUILD.itoa-1.0.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__js_sys__0_3_58",
        url = "https://crates.io/api/v1/crates/js-sys/0.3.58/download",
        type = "tar.gz",
        sha256 = "c3fac17f7123a73ca62df411b1bf727ccc805daa070338fda671c86dac1bdc27",
        strip_prefix = "js-sys-0.3.58",
        build_file = Label("//remote/remote:BUILD.js-sys-0.3.58.bazel"),
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
        name = "raze__log__0_4_17",
        url = "https://crates.io/api/v1/crates/log/0.4.17/download",
        type = "tar.gz",
        sha256 = "abb12e687cfb44aa40f41fc3978ef76448f9b6038cad6aef4259d3c095a2382e",
        strip_prefix = "log-0.4.17",
        build_file = Label("//remote/remote:BUILD.log-0.4.17.bazel"),
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
        name = "raze__memchr__2_5_0",
        url = "https://crates.io/api/v1/crates/memchr/2.5.0/download",
        type = "tar.gz",
        sha256 = "2dffe52ecf27772e601905b7522cb4ef790d2cc203488bbd0e2fe85fcb74566d",
        strip_prefix = "memchr-2.5.0",
        build_file = Label("//remote/remote:BUILD.memchr-2.5.0.bazel"),
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
        name = "raze__mio__0_8_3",
        url = "https://crates.io/api/v1/crates/mio/0.8.3/download",
        type = "tar.gz",
        sha256 = "713d550d9b44d89174e066b7a6217ae06234c10cb47819a88290d2b353c31799",
        strip_prefix = "mio-0.8.3",
        build_file = Label("//remote/remote:BUILD.mio-0.8.3.bazel"),
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
        name = "raze__num_traits__0_2_15",
        url = "https://crates.io/api/v1/crates/num-traits/0.2.15/download",
        type = "tar.gz",
        strip_prefix = "num-traits-0.2.15",
        build_file = Label("//remote/remote:BUILD.num-traits-0.2.15.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__num_cpus__1_13_1",
        url = "https://crates.io/api/v1/crates/num_cpus/1.13.1/download",
        type = "tar.gz",
        strip_prefix = "num_cpus-1.13.1",
        build_file = Label("//remote/remote:BUILD.num_cpus-1.13.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__once_cell__1_12_0",
        url = "https://crates.io/api/v1/crates/once_cell/1.12.0/download",
        type = "tar.gz",
        sha256 = "7709cef83f0c1f58f666e746a08b21e0085f7440fa6a29cc194d68aac97a4225",
        strip_prefix = "once_cell-1.12.0",
        build_file = Label("//remote/remote:BUILD.once_cell-1.12.0.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__openssl__0_10_40",
        url = "https://crates.io/api/v1/crates/openssl/0.10.40/download",
        type = "tar.gz",
        sha256 = "fb81a6430ac911acb25fe5ac8f1d2af1b4ea8a4fdfda0f1ee4292af2e2d8eb0e",
        strip_prefix = "openssl-0.10.40",
        build_file = Label("//remote/remote:BUILD.openssl-0.10.40.bazel"),
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
        name = "raze__openssl_sys__0_9_74",
        url = "https://crates.io/api/v1/crates/openssl-sys/0.9.74/download",
        type = "tar.gz",
        sha256 = "835363342df5fba8354c5b453325b110ffd54044e588c539cf2f20a8014e4cb1",
        strip_prefix = "openssl-sys-0.9.74",
        build_file = Label("//remote/remote:BUILD.openssl-sys-0.9.74.bazel"),
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
        name = "raze__proc_macro2__1_0_39",
        url = "https://crates.io/api/v1/crates/proc-macro2/1.0.39/download",
        type = "tar.gz",
        sha256 = "c54b25569025b7fc9651de43004ae593a75ad88543b17178aa5e1b9c4f15f56f",
        strip_prefix = "proc-macro2-1.0.39",
        build_file = Label("//remote/remote:BUILD.proc-macro2-1.0.39.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__quote__1_0_18",
        url = "https://crates.io/api/v1/crates/quote/1.0.18/download",
        type = "tar.gz",
        sha256 = "a1feb54ed693b93a84e14094943b84b7c4eae204c512b7ccb95ab0c66d278ad1",
        strip_prefix = "quote-1.0.18",
        build_file = Label("//remote/remote:BUILD.quote-1.0.18.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__redox_syscall__0_2_13",
        url = "https://crates.io/api/v1/crates/redox_syscall/0.2.13/download",
        type = "tar.gz",
        sha256 = "62f25bc4c7e55e0b0b7a1d43fb893f4fa1361d0abe38b9ce4f323c2adfe6ef42",
        strip_prefix = "redox_syscall-0.2.13",
        build_file = Label("//remote/remote:BUILD.redox_syscall-0.2.13.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex__1_5_6",
        url = "https://crates.io/api/v1/crates/regex/1.5.6/download",
        type = "tar.gz",
        sha256 = "d83f127d94bdbcda4c8cc2e50f6f84f4b611f69c902699ca385a39c3a75f9ff1",
        strip_prefix = "regex-1.5.6",
        build_file = Label("//remote/remote:BUILD.regex-1.5.6.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__regex_syntax__0_6_26",
        url = "https://crates.io/api/v1/crates/regex-syntax/0.6.26/download",
        type = "tar.gz",
        sha256 = "49b3de9ec5dc0a3417da371aab17d729997c15010e7fd24ff707773a33bddb64",
        strip_prefix = "regex-syntax-0.6.26",
        build_file = Label("//remote/remote:BUILD.regex-syntax-0.6.26.bazel"),
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
        name = "raze__rust_decimal__1_25_0",
        url = "https://crates.io/api/v1/crates/rust_decimal/1.25.0/download",
        type = "tar.gz",
        strip_prefix = "rust_decimal-1.25.0",
        build_file = Label("//remote/remote:BUILD.rust_decimal-1.25.0.bazel"),
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
        name = "raze__schannel__0_1_20",
        url = "https://crates.io/api/v1/crates/schannel/0.1.20/download",
        type = "tar.gz",
        sha256 = "88d6731146462ea25d9244b2ed5fd1d716d25c52e4d54aa4fb0f3c4e9854dbe2",
        strip_prefix = "schannel-0.1.20",
        build_file = Label("//remote/remote:BUILD.schannel-0.1.20.bazel"),
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
        name = "raze__serde__1_0_137",
        url = "https://crates.io/api/v1/crates/serde/1.0.137/download",
        type = "tar.gz",
        sha256 = "61ea8d54c77f8315140a05f4c7237403bf38b72704d031543aa1d16abbf517d1",
        strip_prefix = "serde-1.0.137",
        build_file = Label("//remote/remote:BUILD.serde-1.0.137.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_derive__1_0_137",
        url = "https://crates.io/api/v1/crates/serde_derive/1.0.137/download",
        type = "tar.gz",
        sha256 = "1f26faba0c3959972377d3b2d306ee9f71faee9714294e41bb777f83f88578be",
        strip_prefix = "serde_derive-1.0.137",
        build_file = Label("//remote/remote:BUILD.serde_derive-1.0.137.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_json__1_0_81",
        url = "https://crates.io/api/v1/crates/serde_json/1.0.81/download",
        type = "tar.gz",
        sha256 = "9b7ce2b32a1aed03c558dc61a5cd328f15aff2dbc17daad8fb8af04d2100e15c",
        strip_prefix = "serde_json-1.0.81",
        build_file = Label("//remote/remote:BUILD.serde_json-1.0.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__serde_path_to_error__0_1_7",
        url = "https://crates.io/api/v1/crates/serde_path_to_error/0.1.7/download",
        type = "tar.gz",
        strip_prefix = "serde_path_to_error-0.1.7",
        build_file = Label("//remote/remote:BUILD.serde_path_to_error-0.1.7.bazel"),
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
        name = "raze__slab__0_4_6",
        url = "https://crates.io/api/v1/crates/slab/0.4.6/download",
        type = "tar.gz",
        sha256 = "eb703cfe953bccee95685111adeedb76fabe4e97549a58d16f03ea7b9367bb32",
        strip_prefix = "slab-0.4.6",
        build_file = Label("//remote/remote:BUILD.slab-0.4.6.bazel"),
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
        name = "raze__syn__1_0_96",
        url = "https://crates.io/api/v1/crates/syn/1.0.96/download",
        type = "tar.gz",
        sha256 = "0748dd251e24453cb8717f0354206b91557e4ec8703673a4b30208f2abaf1ebf",
        strip_prefix = "syn-1.0.96",
        build_file = Label("//remote/remote:BUILD.syn-1.0.96.bazel"),
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
        name = "raze__termcolor__1_1_3",
        url = "https://crates.io/api/v1/crates/termcolor/1.1.3/download",
        type = "tar.gz",
        sha256 = "bab24d30b911b2376f3a13cc2cd443142f0c81dda04c118693e35b3835757755",
        strip_prefix = "termcolor-1.1.3",
        build_file = Label("//remote/remote:BUILD.termcolor-1.1.3.bazel"),
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
        name = "raze__tokio__1_19_2",
        url = "https://crates.io/api/v1/crates/tokio/1.19.2/download",
        type = "tar.gz",
        sha256 = "c51a52ed6686dd62c320f9b89299e9dfb46f730c7a48e635c19f21d116cb1439",
        strip_prefix = "tokio-1.19.2",
        build_file = Label("//remote/remote:BUILD.tokio-1.19.2.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tokio_macros__1_8_0",
        url = "https://crates.io/api/v1/crates/tokio-macros/1.8.0/download",
        type = "tar.gz",
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
        strip_prefix = "toml-0.5.9",
        build_file = Label("//remote/remote:BUILD.toml-0.5.9.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__tower_service__0_3_1",
        url = "https://crates.io/api/v1/crates/tower-service/0.3.1/download",
        type = "tar.gz",
        sha256 = "360dfd1d6d30e05fda32ace2c8c70e9c0a9da713275777f5a4dbb8a1893930c6",
        strip_prefix = "tower-service-0.3.1",
        build_file = Label("//remote/remote:BUILD.tower-service-0.3.1.bazel"),
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
        name = "raze__tracing_core__0_1_27",
        url = "https://crates.io/api/v1/crates/tracing-core/0.1.27/download",
        type = "tar.gz",
        sha256 = "7709595b8878a4965ce5e87ebf880a7d39c9afc6837721b21a5a816a8117d921",
        strip_prefix = "tracing-core-0.1.27",
        build_file = Label("//remote/remote:BUILD.tracing-core-0.1.27.bazel"),
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
        name = "raze__unicode_bidi__0_3_8",
        url = "https://crates.io/api/v1/crates/unicode-bidi/0.3.8/download",
        type = "tar.gz",
        sha256 = "099b7128301d285f79ddd55b9a83d5e6b9e97c92e0ea0daebee7263e932de992",
        strip_prefix = "unicode-bidi-0.3.8",
        build_file = Label("//remote/remote:BUILD.unicode-bidi-0.3.8.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_ident__1_0_1",
        url = "https://crates.io/api/v1/crates/unicode-ident/1.0.1/download",
        type = "tar.gz",
        sha256 = "5bd2fe26506023ed7b5e1e315add59d6f584c621d037f9368fea9cfb988f368c",
        strip_prefix = "unicode-ident-1.0.1",
        build_file = Label("//remote/remote:BUILD.unicode-ident-1.0.1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__unicode_normalization__0_1_19",
        url = "https://crates.io/api/v1/crates/unicode-normalization/0.1.19/download",
        type = "tar.gz",
        sha256 = "d54590932941a9e9266f0832deed84ebe1bf2e4c9e4a3554d393d18f5e854bf9",
        strip_prefix = "unicode-normalization-0.1.19",
        build_file = Label("//remote/remote:BUILD.unicode-normalization-0.1.19.bazel"),
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
        name = "raze__vcpkg__0_2_15",
        url = "https://crates.io/api/v1/crates/vcpkg/0.2.15/download",
        type = "tar.gz",
        sha256 = "accd4ea62f7bb7a82fe23066fb0957d48ef677f6eeb8215f372f52e48bb32426",
        strip_prefix = "vcpkg-0.2.15",
        build_file = Label("//remote/remote:BUILD.vcpkg-0.2.15.bazel"),
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
        name = "raze__wasi__0_11_0_wasi_snapshot_preview1",
        url = "https://crates.io/api/v1/crates/wasi/0.11.0+wasi-snapshot-preview1/download",
        type = "tar.gz",
        sha256 = "9c8d87e72b64a3b4db28d11ce29237c246188f4f51057d65a7eab63b7987e423",
        strip_prefix = "wasi-0.11.0+wasi-snapshot-preview1",
        build_file = Label("//remote/remote:BUILD.wasi-0.11.0+wasi-snapshot-preview1.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen__0_2_81",
        url = "https://crates.io/api/v1/crates/wasm-bindgen/0.2.81/download",
        type = "tar.gz",
        sha256 = "7c53b543413a17a202f4be280a7e5c62a1c69345f5de525ee64f8cfdbc954994",
        strip_prefix = "wasm-bindgen-0.2.81",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-0.2.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_backend__0_2_81",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-backend/0.2.81/download",
        type = "tar.gz",
        sha256 = "5491a68ab4500fa6b4d726bd67408630c3dbe9c4fe7bda16d5c82a1fd8c7340a",
        strip_prefix = "wasm-bindgen-backend-0.2.81",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-backend-0.2.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_futures__0_4_31",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-futures/0.4.31/download",
        type = "tar.gz",
        sha256 = "de9a9cec1733468a8c657e57fa2413d2ae2c0129b95e87c5b72b8ace4d13f31f",
        strip_prefix = "wasm-bindgen-futures-0.4.31",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-futures-0.4.31.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_macro__0_2_81",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-macro/0.2.81/download",
        type = "tar.gz",
        sha256 = "c441e177922bc58f1e12c022624b6216378e5febc2f0533e41ba443d505b80aa",
        strip_prefix = "wasm-bindgen-macro-0.2.81",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-macro-0.2.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_macro_support__0_2_81",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-macro-support/0.2.81/download",
        type = "tar.gz",
        sha256 = "7d94ac45fcf608c1f45ef53e748d35660f168490c10b23704c7779ab8f5c3048",
        strip_prefix = "wasm-bindgen-macro-support-0.2.81",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-macro-support-0.2.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__wasm_bindgen_shared__0_2_81",
        url = "https://crates.io/api/v1/crates/wasm-bindgen-shared/0.2.81/download",
        type = "tar.gz",
        sha256 = "6a89911bd99e5f3659ec4acf9c4d93b0a90fe4a2a11f15328472058edc5261be",
        strip_prefix = "wasm-bindgen-shared-0.2.81",
        build_file = Label("//remote/remote:BUILD.wasm-bindgen-shared-0.2.81.bazel"),
    )

    maybe(
        http_archive,
        name = "raze__web_sys__0_3_58",
        url = "https://crates.io/api/v1/crates/web-sys/0.3.58/download",
        type = "tar.gz",
        sha256 = "2fed94beee57daf8dd7d51f2b15dc2bcde92d7a72304cdf662a4371008b71b90",
        strip_prefix = "web-sys-0.3.58",
        build_file = Label("//remote/remote:BUILD.web-sys-0.3.58.bazel"),
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
