"""Diagnostic tests: verify Docker container primitives work on RBE.

Each test isolates a single capability so failures pinpoint exactly what's broken.
Tests run against both debian-slim (baseline) and freecad-test (our image) to
distinguish RBE Docker issues from image-specific problems.
"""

import io
import tarfile
from pathlib import Path

import pytest
import pytest_bazel

from third_party.debian_slim.rlocations import IMAGE_TAG as DEBIAN_IMAGE_TAG, TARBALL as DEBIAN_TARBALL
from util.oci import load_image
from util.testing.container_logs import LoggedContainer

_FREECAD_IMAGE_TAG = "freecad-test:pinned"
_FREECAD_TARBALL = "_main/skills/freecad/freecad_test_load/tarball.tar"

_IMAGES = [
    pytest.param((DEBIAN_TARBALL, DEBIAN_IMAGE_TAG), id="debian-slim"),
    pytest.param((_FREECAD_TARBALL, _FREECAD_IMAGE_TAG), id="freecad-test"),
]


@pytest.fixture(params=_IMAGES)
def container_image(request: pytest.FixtureRequest) -> tuple[str, str]:
    """Load image and return (tarball, tag) for parametrized tests."""
    tarball, tag = request.param
    load_image(tarball)
    return tarball, tag


def test_exec(container_image: tuple[str, str]) -> None:
    """Verify exec runs a command and returns output."""
    _, tag = container_image
    with LoggedContainer(tag, test_name=f"exec-{tag}", command="sleep infinity") as container:
        result = container.exec("echo EXEC_OK")
        assert result.exit_code == 0
        assert b"EXEC_OK" in result.output


def test_volume_mount_read(container_image: tuple[str, str], tmp_path: Path) -> None:
    """Verify container can read a host-mounted file."""
    _, tag = container_image
    test_file = tmp_path / "input.txt"
    test_file.write_text("MOUNT_READ_OK")
    with LoggedContainer(
        tag,
        test_name=f"mount-read-{tag}",
        command="sleep infinity",
        volumes=[(str(test_file), "/work/input.txt", "ro")],
    ) as container:
        result = container.exec("cat /work/input.txt")
        assert result.exit_code == 0
        assert b"MOUNT_READ_OK" in result.output


def test_volume_mount_write(container_image: tuple[str, str], tmp_path: Path) -> None:
    """Verify container can write a file visible on the host via volume mount."""
    _, tag = container_image
    with LoggedContainer(
        tag, test_name=f"mount-write-{tag}", command="sleep infinity", volumes=[(str(tmp_path), "/output", "rw")]
    ) as container:
        result = container.exec('bash -c "echo MOUNT_WRITE_OK > /output/test.txt"')
        assert result.exit_code == 0
    assert (tmp_path / "test.txt").read_text().strip() == "MOUNT_WRITE_OK"


def test_put_archive_and_cat(container_image: tuple[str, str]) -> None:
    """Verify put_archive copies a file in and cat reads it back."""
    _, tag = container_image
    with LoggedContainer(tag, test_name=f"put-cat-{tag}", command="sleep infinity") as container:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            data = b"PUT_ARCHIVE_OK"
            info = tarfile.TarInfo(name="test.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        container.exec("mkdir -p /work")
        container.get_wrapped_container().put_archive("/work", buf.read())

        result = container.exec("cat /work/test.txt")
        assert result.exit_code == 0
        assert b"PUT_ARCHIVE_OK" in result.output


if __name__ == "__main__":
    pytest_bazel.main()
