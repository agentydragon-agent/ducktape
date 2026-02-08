"""OCI image helpers for py_image_layer containers.

Uses aspect_rules_py's py_image_layer for multi-layer OCI images
(interpreter, site-packages, app code) on a debian-slim base with bash.
The aspect py_binary launcher is a bash script that sets up a venv and
exec's the Python interpreter, so the base image must provide /bin/bash.
"""

_PY_IMAGE_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}

def py_image_entrypoint(binary_name, binary_package = None):
    """Compute entrypoint for an OCI image running an aspect py_binary.

    Args:
        binary_name: Name of the aspect_py_binary target (e.g., "critic_bin").
        binary_package: Bazel package path. Defaults to calling BUILD's package.

    Returns:
        Entrypoint list for oci_image.
    """
    pkg = binary_package or native.package_name()
    return ["/{}/{}".format(pkg, binary_name)]

def py_image_env(extra_env = {}):
    """Standard env dict for py_image_layer containers.

    Args:
        extra_env: Additional env vars to merge.

    Returns:
        Env dict for oci_image.
    """
    env = dict(_PY_IMAGE_ENV)
    env.update(extra_env)
    return env
