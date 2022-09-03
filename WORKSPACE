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

http_archive(
    name = "rules_haskell",
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

stack_snapshot(
    name = "stackage",
    # For some reason required to make attoparsec work.
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
)
