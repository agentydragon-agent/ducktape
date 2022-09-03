load("@rules_haskell//haskell:defs.bzl", "haskell_binary")

haskell_binary(
    name = "site",
    srcs = ["site.hs"],
    deps = [
        "@stackage//:base",
        "@stackage//:hakyll",
    ],
)
