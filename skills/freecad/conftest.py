"""Shared fixtures for FreeCAD tests."""

import pytest
import pytest_bazel

from util.oci import OciImage, load_oci_image

FREECAD_TEST = OciImage("_main/skills/freecad/freecad_test.rloc", "freecad-test:pinned")


@pytest.fixture(scope="session")
def freecad_image() -> str:
    """Load FreeCAD test image into Docker daemon and return its tag."""
    return load_oci_image(FREECAD_TEST)
