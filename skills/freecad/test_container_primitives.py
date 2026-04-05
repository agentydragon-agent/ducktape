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
from opentelemetry import trace

from skills.freecad.conftest import FREECAD_TEST
from third_party.containers.rlocations import DEBIAN_SLIM
from util.oci import OciImage, load_oci_image
from util.testing.container_logs import LoggedContainer

_IMAGES = [pytest.param(DEBIAN_SLIM, id="debian-slim"), pytest.param(FREECAD_TEST, id="freecad-test")]

tracer = trace.get_tracer(__name__)


@pytest.fixture(params=_IMAGES)
def container_image(request: pytest.FixtureRequest) -> OciImage:
    """Load image and return OciImage for parametrized tests."""
    image: OciImage = request.param
    with tracer.start_as_current_span("load_oci_image", attributes={"tag": image.tag}):
        load_oci_image(image)
    return image


def test_exec(container_image: OciImage) -> None:
    """Verify exec runs a command and returns output."""
    tag = container_image.tag
    with LoggedContainer(tag, test_name=f"exec-{tag}", command="sleep infinity") as container:
        result = container.exec("echo EXEC_OK")
        assert result.exit_code == 0
        assert b"EXEC_OK" in result.output


def test_volume_mount_read(container_image: OciImage, tmp_path: Path) -> None:
    """Verify container can read a host-mounted file."""
    tag = container_image.tag
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


def test_volume_mount_write(container_image: OciImage, tmp_path: Path) -> None:
    """Verify container can write a file visible on the host via volume mount."""
    tag = container_image.tag
    with LoggedContainer(
        tag, test_name=f"mount-write-{tag}", command="sleep infinity", volumes=[(str(tmp_path), "/output", "rw")]
    ) as container:
        result = container.exec('bash -c "echo MOUNT_WRITE_OK > /output/test.txt"')
        assert result.exit_code == 0
    assert (tmp_path / "test.txt").read_text().strip() == "MOUNT_WRITE_OK"


def test_put_archive_and_cat(container_image: OciImage) -> None:
    """Verify put_archive copies a file in and cat reads it back."""
    tag = container_image.tag
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
