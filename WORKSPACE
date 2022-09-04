workspace(
    name = "ducktape",
    managed_directories = {"@npm": ["node_modules"]},
)

load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

http_archive(
    name = "rules_python",
    sha256 = "954aa89b491be4a083304a2cb838019c8b8c3720a7abb9c4cb81ac7a24230cea",
    urls = [
        "https://mirror.bazel.build/github.com/bazelbuild/rules_python/releases/download/0.4.0/rules_python-0.4.0.tar.gz",
        "https://github.com/bazelbuild/rules_python/releases/download/0.4.0/rules_python-0.4.0.tar.gz",
    ],
)

load("@rules_python//python:pip.bzl", "pip_parse")

pip_parse(
    name = "my_deps",
    requirements_lock = "//:requirements_lock.txt",
)

load("@my_deps//:requirements.bzl", "install_deps")

install_deps()

load("@bazel_tools//tools/build_defs/repo:git.bzl", "git_repository")
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

# To find additional information on this release or newer ones visit:
# https://github.com/bazelbuild/rules_rust/releases
git_repository(
    name = "rules_rust",
    commit = "81590f4b6a423f5369bd060d26171289d71232ae",
    remote = "https://github.com/bazelbuild/rules_rust",
    shallow_since = "1654686539 -0700",
)

load("@rules_rust//rust:repositories.bzl", "rules_rust_dependencies", "rust_register_toolchains")

rules_rust_dependencies()

rust_register_toolchains()

load("//remote:crates.bzl", "raze_fetch_remote_crates")

raze_fetch_remote_crates()

# TODO: maybe run cargo-raze via Bazel?

# Haskell setup taken from https://www.tweag.io/blog/2020-05-06-convert-haskell-project-to-bazel/
http_archive(
    name = "rules_haskell",
    sha256 = "aba3c16015a2363b16e2f867bdc5c792fa71c68cb97d8fe95fddc41e409d6ba8",
    strip_prefix = "rules_haskell-0.15",
    urls = ["https://github.com/tweag/rules_haskell/archive/v0.15.tar.gz"],
)

load(
    "@rules_haskell//haskell:repositories.bzl",
    "rules_haskell_dependencies",
)

# Setup rules_haskell.
rules_haskell_dependencies()

load(
    "@rules_haskell//haskell:toolchain.bzl",
    "rules_haskell_toolchains",
)

# Download a GHC binary distribution from haskell.org
# and register it as an available toolchain.
rules_haskell_toolchains(version = "9.0.2")

load(
    "@rules_haskell//haskell:cabal.bzl",
    "stack_snapshot",
)

# xml-conduit fix pulled from:
# https://github.com/digital-asset/daml/blob/db4de4e8c54e5ca5c482ecc0f855e14d4e89f6b2/bazel-haskell-deps.bzl
XML_CONDUIT_VERSION = "1.9.1.1"

http_archive(
    name = "xml-conduit",
    build_file_content = """
load("@rules_haskell//haskell:cabal.bzl", "haskell_cabal_library")
load("@stackage//:packages.bzl", "packages")
haskell_cabal_library(
    name = "xml-conduit",
    version = packages["xml-conduit"].version,
    srcs = glob(["**"]),
    haddock = False,
    deps = packages["xml-conduit"].deps,
    # For some reason we need to manually add the setup dep here.
    setup_deps = ["@stackage//:cabal-doctest"],
    verbose = False,
    visibility = ["//visibility:public"],
)
""",
    sha256 = "bdb117606c0b56ca735564465b14b50f77f84c9e52e31d966ac8d4556d3ff0ff",
    strip_prefix = "xml-conduit-{}".format(XML_CONDUIT_VERSION),
    urls = ["http://hackage.haskell.org/package/xml-conduit-{version}/xml-conduit-{version}.tar.gz".format(version = XML_CONDUIT_VERSION)],
)

stack_snapshot(
    name = "stackage",
    # For some reason required to make attoparsec work. Fix pulled from:
    # https://github.com/digital-asset/daml/blob/db4de4e8c54e5ca5c482ecc0f855e14d4e89f6b2/bazel-haskell-deps.bzl
    components = {
        "attoparsec": [
            "lib:attoparsec",
            "lib:attoparsec-internal",
        ],
    },
    components_dependencies = {
        "attoparsec": """{"lib:attoparsec": ["lib:attoparsec-internal"]}""",
    },
    packages = [
        "base",
        "hakyll",
    ],
    snapshot = "lts-19.17",
    vendored_packages = {
        "xml-conduit": "@xml-conduit//:xml-conduit",
    },
)
