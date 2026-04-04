"""Pytest fixture for the debian-slim base image (//third_party/debian_slim:image_info)."""

import pytest

from third_party.debian_slim.rlocations import INFO
from util.oci import load_oci_image


@pytest.fixture(scope="session")
def debian_slim_image():
    """Load debian-slim image into Docker daemon and return its tag."""
    return load_oci_image(INFO)
