"""Golden render test for the claude-quota GNOME extension.

Boots the gnome-shell test container (built by
//gnome-extensions/test_image:gnome_shell_test_image), bind-mounts the
extension source and a fixture JSON, runs the in-image render.sh which
launches gnome-shell under Xvfb and screenshots the panel via D-Bus,
then compares the PNG to a checked-in golden.

Update flow when the rendering changes intentionally:

    bbr test //gnome-extensions/claude-quota:test_render \\
        --test_env=UPDATE_GOLDEN=1 \\
        --remote_download_outputs=toplevel --nocache_test_results
    cp bb-out/bazel-testlogs/gnome-extensions/claude-quota/test_render/test.outputs/panel_both_ok.png \\
       gnome-extensions/claude-quota/__snapshots__/panel_both_ok.png

    # eyeball the new golden, commit, then re-run without UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import docker.models.containers
import pytest
import pytest_bazel
from PIL import Image, ImageChops
from testcontainers.core.container import DockerContainer

from util.bazel.runfiles import get_required_path
from util.oci import OciImage, load_oci_image
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

_GNOME_SHELL_TEST = OciImage("_main/gnome-extensions/test_image/gnome_shell_test.rloc", "gnome-shell-test:pinned")

# Files that make up the extension as gnome-shell loads it.
_EXTENSION_FILES = ["extension.js", "metadata.json", "stylesheet.css"]
_EXTENSION_ICON_FILES = ["icons/claude-symbolic.svg", "icons/openai-symbolic.svg"]

# Fraction of pixels that may differ between the actual and golden renders.
# Same tolerance as the Puppeteer visual tests in
# util/testing/frontend_visual/visual-test-lib.mjs.
_PIXEL_DIFF_TOLERANCE = 0.02

# Per-pixel intensity threshold (0-255) below which pixels are considered
# "equal". Absorbs sub-pixel font rasterization noise without masking real
# layout/colour changes.
_PIXEL_INTENSITY_THRESHOLD = 16

# Width (px) of the right-edge slice of the panel that we keep as the
# golden. The full Xvfb display is 1920x40 and includes the GNOME date
# menu in the centre, which renders the current real time and would make
# the golden comparison flake on every run. The claude-quota indicator
# lives at the right side of the panel, so we screenshot the whole panel
# but only diff the right-edge crop.
_PANEL_CROP_WIDTH = 250


@pytest.fixture(scope="module")
def gnome_shell_test_image() -> str:
    return load_oci_image(_GNOME_SHELL_TEST)


@contextlib.contextmanager
def _staged_extension_dir() -> Iterator[Path]:
    """Copy the extension files into a single tempdir for bind-mounting."""
    src_root = get_required_path(f"_main/gnome-extensions/claude-quota/{_EXTENSION_FILES[0]}").parent
    with tempfile.TemporaryDirectory(prefix="claude-quota-ext-") as d:
        dest = Path(d)
        for rel in _EXTENSION_FILES:
            shutil.copy(src_root / rel, dest / rel)
        (dest / "icons").mkdir()
        for rel in _EXTENSION_ICON_FILES:
            shutil.copy(src_root / rel, dest / rel)
        yield dest


@contextlib.contextmanager
def _render_container(
    image_tag: str, extension_dir: Path, fixture_path: Path, out_dir: Path
) -> Iterator[DockerContainer]:
    """Run the test container with the extension + fixture mounted in."""
    container = DockerContainer(image_tag)
    container.with_volume_mapping(
        str(extension_dir), "/usr/share/gnome-shell/extensions/claude-quota@allegedly.works", "ro"
    )
    container.with_volume_mapping(str(fixture_path.parent), "/fixtures", "ro")
    container.with_volume_mapping(str(out_dir), "/out", "rw")
    with container:
        yield container


def _exec_render(container: DockerContainer, fixture_name: str, out_name: str) -> None:
    """Invoke /usr/local/bin/render.sh inside the container; raise on failure."""
    raw: docker.models.containers.Container = container.get_wrapped_container()
    cmd = ["/usr/local/bin/render.sh", f"/fixtures/{fixture_name}", f"/out/{out_name}"]
    result = raw.exec_run(cmd, demux=True)
    stdout, stderr = result.output

    # Always pull shell.log so reviewers / golden-update flow can see what
    # the GNOME shell actually loaded.
    out_dir = undeclared_outputs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    shell_log = raw.exec_run(["cat", "/tmp/shell.log"], demux=True)
    (out_dir / "shell.log").write_bytes((shell_log.output[0] or b"") + (shell_log.output[1] or b""))

    if result.exit_code != 0:
        (out_dir / "render.stdout").write_bytes(stdout or b"")
        (out_dir / "render.stderr").write_bytes(stderr or b"")
        pytest.fail(
            f"render.sh exit={result.exit_code}\n"
            f"stdout: {(stdout or b'').decode(errors='replace')}\n"
            f"stderr: {(stderr or b'').decode(errors='replace')}\n"
            f"see undeclared outputs for shell.log."
        )


def _diff_fraction(actual_path: Path, expected_path: Path, diff_path: Path) -> float:
    """Write a diff PNG and return the fraction of mismatched pixels."""
    actual = Image.open(actual_path).convert("RGBA")
    expected = Image.open(expected_path).convert("RGBA")
    if actual.size != expected.size:
        raise AssertionError(f"size mismatch: actual={actual.size} expected={expected.size}")

    diff = ImageChops.difference(actual, expected).convert("L")
    # Highlight differing pixels (>= threshold) as bright red on top of the actual.
    mask = diff.point(lambda v: 255 if v >= _PIXEL_INTENSITY_THRESHOLD else 0)
    overlay = actual.copy()
    red = Image.new("RGBA", actual.size, (255, 0, 0, 255))
    overlay.paste(red, mask=mask)
    overlay.save(diff_path)

    differing = sum(1 for v in list(mask.getdata()) if v == 255)
    return differing / (actual.size[0] * actual.size[1])


def test_panel_both_ok(gnome_shell_test_image: str) -> None:
    fixture_path = get_required_path("_main/gnome-extensions/claude-quota/test_fixtures/panel_both_ok.json")
    update_golden = os.environ.get("UPDATE_GOLDEN") == "1"

    with tempfile.TemporaryDirectory(prefix="claude-quota-out-") as out_dir_str:
        out_dir = Path(out_dir_str)
        out_dir.chmod(0o777)  # gnome-shell writes the screenshot as a different uid
        with (
            _staged_extension_dir() as extension_dir,
            _render_container(gnome_shell_test_image, extension_dir, fixture_path, out_dir) as container,
        ):
            _exec_render(container, fixture_path.name, "panel_both_ok.png")

        full_path = out_dir / "panel_both_ok.png"
        assert full_path.exists(), f"render.sh did not produce {full_path}"

        # Crop to the right-edge slice where our extension lives, so the
        # GNOME date menu in the centre doesn't poison the golden.
        full = Image.open(full_path)
        actual_path = out_dir / "panel_both_ok.cropped.png"
        full.crop((full.width - _PANEL_CROP_WIDTH, 0, full.width, full.height)).save(actual_path)

        uo = undeclared_outputs_dir()
        uo.mkdir(parents=True, exist_ok=True)

        if update_golden:
            # Skip comparison; just publish the rendered PNG so the user can
            # cp it into __snapshots__/.
            shutil.copy(actual_path, uo / "panel_both_ok.png")
            logger.warning("UPDATE_GOLDEN=1: wrote new golden to %s", uo / "panel_both_ok.png")
            return

        try:
            expected_path = get_required_path("_main/gnome-extensions/claude-quota/__snapshots__/panel_both_ok.png")
        except RuntimeError:
            shutil.copy(actual_path, uo / "panel_both_ok.actual.png")
            pytest.fail(
                "No golden checked in yet. Re-run with --test_env=UPDATE_GOLDEN=1, then cp the produced "
                "panel_both_ok.png from undeclared outputs into "
                "gnome-extensions/claude-quota/__snapshots__/."
            )

        diff_path = uo / "panel_both_ok.diff.png"
        fraction = _diff_fraction(actual_path, expected_path, diff_path)
        if fraction > _PIXEL_DIFF_TOLERANCE:
            shutil.copy(actual_path, uo / "panel_both_ok.actual.png")
            shutil.copy(expected_path, uo / "panel_both_ok.expected.png")
            pytest.fail(
                f"panel_both_ok render diverged: {fraction:.2%} of pixels differ "
                f"(tolerance {_PIXEL_DIFF_TOLERANCE:.0%}). "
                f"Inspect panel_both_ok.{{actual,expected,diff}}.png in undeclared outputs. "
                f"To accept the new render, re-run with --test_env=UPDATE_GOLDEN=1 and cp "
                f"the produced PNG into gnome-extensions/claude-quota/__snapshots__/."
            )


if __name__ == "__main__":
    pytest_bazel.main()
