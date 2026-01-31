"""Docker image loading utilities for tests.

Provides a unified interface for loading OCI images from Bazel oci_load targets
into the local Docker daemon during test execution.
"""

from __future__ import annotations

import os
import subprocess

import pytest

import runfiles


def load_bazel_image(load_script_path: str, image_tag: str) -> str:
    """Load an OCI image from a Bazel oci_load target.

    Args:
        load_script_path: Relative path to the load.sh script (e.g., "third_party/python_slim/load.sh")
        image_tag: The expected image tag after loading (e.g., "python-slim:test")

    Returns:
        The image tag that was loaded.

    Raises:
        RuntimeError: If loading the image fails.
    """
    load_script = runfiles.get_required_path(f"_main/{load_script_path}")

    result = subprocess.run(
        [load_script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DOCKER_CLI_EXPERIMENTAL": "enabled"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to load image {image_tag}: {result.stderr}")

    return image_tag


# Image tags and load scripts for shared test images
PYTHON_SLIM_IMAGE_TAG = "python-slim:test"
PYTHON_SLIM_LOAD_SCRIPT = "third_party/python_slim/load.sh"


@pytest.fixture(scope="session")
def python_slim_image():
    """Load python-slim image from Bazel //third_party/python_slim:load target."""
    return load_bazel_image(PYTHON_SLIM_LOAD_SCRIPT, PYTHON_SLIM_IMAGE_TAG)
