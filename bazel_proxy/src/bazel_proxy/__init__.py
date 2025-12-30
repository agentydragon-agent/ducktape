"""Bazel proxy for TLS-inspecting proxy environments.

This package provides a local proxy that adds authentication headers
for upstream TLS-inspecting proxies, enabling Bazel to access BCR.

IMPORTANT: This package must not have any non-stdlib dependencies
because it's used by session-start hooks which run before package
installation.
"""

from bazel_proxy.proxy import main

__all__ = ["main"]
