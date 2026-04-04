"""Runfiles rlocation constants for pre-built container images.

These correspond to the oci_tarball targets in this package's BUILD.bazel.
Test fixtures use these with util.oci.load_oci_image() to pre-load images
into the Docker daemon for Testcontainers.
"""

POSTGRES_18 = "_main/third_party/containers/postgres_18.json"
PYTHON_3_13_SLIM = "_main/third_party/containers/python_3_13_slim.json"
REGISTRY_2 = "_main/third_party/containers/registry_2.json"
RYUK = "_main/third_party/containers/ryuk.json"
