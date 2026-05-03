"""Golden render tests for the claude-quota GNOME extension panel.

Boots the gnome-shell test container (built by
//gnome-extensions/test_image:gnome_shell_test_image), unzips the
extension's distribution zip (//gnome-extensions/claude-quota:claude-quota_zip)
into a tempdir for bind-mounting, runs the in-image render.sh which
launches gnome-shell under Xvfb and screenshots the panel via scrot,
crops to the right-edge slice where the indicator lives, then compares
the PNG to a checked-in golden via util.testing.png_diff.

The fixture matrix exercises each branch of the renderer in
extension.js: the four pace-deviation tints (cool/ok/warn/hot), the
short-window absolute-hot override, mixed per-provider state, the
error short-circuit, and the no-data initial state.

Update flow when the rendering changes intentionally:

    bbr test //gnome-extensions/claude-quota:test_render \\
        --test_env=UPDATE_GOLDEN=1 \\
        --remote_download_outputs=toplevel --nocache_test_results

    INV=$(cat ~/.cache/bbr/last_invocation_id)
    for f in panel_both_ok panel_both_cool panel_both_warn panel_both_hot \\
             panel_short_hot panel_mixed panel_error panel_no_data; do
      bbapi artifact "$INV" "$f.png" \\
        > "gnome-extensions/claude-quota/__snapshots__/$f.png"
    done

    # Eyeball, commit, then re-run without UPDATE_GOLDEN=1 to confirm green.
"""

from __future__ import annotations

import logging
import os
import shutil
import zipfile
from pathlib import Path

import docker.models.containers
import pytest
import pytest_bazel
from PIL import Image
from testcontainers.core.container import DockerContainer

from util.bazel.runfiles import get_required_path
from util.oci import OciImage, load_oci_image
from util.testing.png_diff import assert_png_matches_golden
from util.testing.undeclared_outputs import undeclared_outputs_dir

logger = logging.getLogger(__name__)

_GNOME_SHELL_TEST = OciImage("_main/gnome-extensions/test_image/gnome_shell_test.rloc", "gnome-shell-test:pinned")
_EXTENSION_ZIP = "_main/gnome-extensions/claude-quota/claude-quota.zip"
_EXTENSION_UUID = "claude-quota@allegedly.works"

# Width (px) of the right-edge slice of the panel that we keep as the
# golden. The full Xvfb display is 1920x40 and includes the GNOME date
# menu in the centre, which renders the current real time and would make
# the golden comparison flake on every run. The claude-quota indicator
# lives at the right side of the panel, so we screenshot the whole panel
# but only diff the right-edge crop.
_PANEL_CROP_WIDTH = 250

_FIXTURES = [
    "panel_both_ok",
    "panel_both_cool",
    "panel_both_warn",
    "panel_both_hot",
    "panel_short_hot",
    "panel_mixed",
    "panel_error",
    "panel_no_data",
]


@pytest.fixture(scope="module")
def gnome_shell_test_image() -> str:
    return load_oci_image(_GNOME_SHELL_TEST)


@pytest.fixture(scope="module")
def extension_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Unzip the distribution zip into a single dir for bind-mounting."""
    dest = tmp_path_factory.mktemp("claude-quota-ext")
    with zipfile.ZipFile(get_required_path(_EXTENSION_ZIP)) as z:
        z.extractall(dest)
    return dest


def _render_container(image_tag: str, extension_dir: Path, fixture_path: Path, out_dir: Path) -> DockerContainer:
    container = DockerContainer(image_tag)
    container.with_volume_mapping(str(extension_dir), f"/usr/share/gnome-shell/extensions/{_EXTENSION_UUID}", "ro")
    container.with_volume_mapping(str(fixture_path.parent), "/fixtures", "ro")
    container.with_volume_mapping(str(out_dir), "/out", "rw")
    return container


def _exec_render(container: DockerContainer, fixture_name: str, out_name: str, log_dir: Path) -> None:
    """Invoke /usr/local/bin/render.sh inside the container; raise on failure."""
    raw: docker.models.containers.Container = container.get_wrapped_container()
    cmd = ["/usr/local/bin/render.sh", f"/fixtures/{fixture_name}", f"/out/{out_name}"]
    result = raw.exec_run(cmd, demux=True)
    stdout, stderr = result.output

    # Always pull shell.log so reviewers / golden-update flow can see what
    # the GNOME shell actually loaded. Filename is keyed by the output
    # name so parametrized fixtures don't trample each other's logs.
    log_stem = Path(out_name).stem
    shell_log = raw.exec_run(["cat", "/tmp/shell.log"], demux=True)
    (log_dir / f"{log_stem}.shell.log").write_bytes((shell_log.output[0] or b"") + (shell_log.output[1] or b""))

    if result.exit_code != 0:
        (log_dir / f"{log_stem}.render.stdout").write_bytes(stdout or b"")
        (log_dir / f"{log_stem}.render.stderr").write_bytes(stderr or b"")
        pytest.fail(
            f"render.sh exit={result.exit_code} for {fixture_name}\n"
            f"stdout: {(stdout or b'').decode(errors='replace')}\n"
            f"stderr: {(stderr or b'').decode(errors='replace')}\n"
            f"see undeclared outputs for {log_stem}.shell.log."
        )


@pytest.fixture
def undeclared_dir() -> Path:
    out = undeclared_outputs_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_panel(
    gnome_shell_test_image: str, extension_dir: Path, undeclared_dir: Path, tmp_path: Path, fixture_name: str
) -> None:
    fixture_path = get_required_path(f"_main/gnome-extensions/claude-quota/test_fixtures/{fixture_name}.json")
    out_name = f"{fixture_name}.png"
    update_golden = os.environ.get("UPDATE_GOLDEN") == "1"

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_dir.chmod(0o777)  # gnome-shell writes the screenshot as a different uid

    with _render_container(gnome_shell_test_image, extension_dir, fixture_path, out_dir) as container:
        _exec_render(container, fixture_path.name, out_name, undeclared_dir)

    full_path = out_dir / out_name
    assert full_path.exists(), f"render.sh did not produce {full_path}"

    # Crop to the right-edge slice where our extension lives, so the
    # GNOME date menu in the centre doesn't poison the golden.
    full = Image.open(full_path)
    actual_path = tmp_path / f"{fixture_name}.cropped.png"
    full.crop((full.width - _PANEL_CROP_WIDTH, 0, full.width, full.height)).save(actual_path)

    if update_golden:
        # Skip comparison; just publish the rendered PNG so the user can
        # cp it into __snapshots__/.
        shutil.copy(actual_path, undeclared_dir / out_name)
        logger.warning("UPDATE_GOLDEN=1: wrote new golden to %s", undeclared_dir / out_name)
        return

    try:
        expected_path = get_required_path(f"_main/gnome-extensions/claude-quota/__snapshots__/{out_name}")
    except RuntimeError:
        shutil.copy(actual_path, undeclared_dir / f"{fixture_name}.actual.png")
        pytest.fail(
            f"No golden checked in for {fixture_name}. Re-run with --test_env=UPDATE_GOLDEN=1, "
            f"then cp the produced {out_name} from undeclared outputs into "
            f"gnome-extensions/claude-quota/__snapshots__/."
        )

    assert_png_matches_golden(actual_path, expected_path, name=fixture_name, out_dir=undeclared_dir)


if __name__ == "__main__":
    pytest_bazel.main()
