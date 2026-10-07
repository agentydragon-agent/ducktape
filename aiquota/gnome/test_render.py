"""Render-health + PR-visuals publication tests for the ai-quota GNOME extension.

A single test container (//gnome/test_image:gnome_shell_test_image)
is started once per module: boot.sh inside it brings up Xvfb, the
postinst-equivalent caches, and a long-lived dbus session bus, then
blocks. A single gnome-shell is started inside that container (also
once per module) and the extension exports a session-bus interface
(works.allegedly.AiQuotaTest, gated on AI_QUOTA_FIXTURE) that
lets this driver swap fixture state, open/close the popup menu, and
query the menu's screen geometry.

Each fixture renders to a single PNG capturing both the panel
indicator (with menu open, so the button shows its active state) and
the open popup menu below it. The crop spans from the menu's left edge
to the right edge of the screen and from the top of the panel to the
bottom of the menu — so reviewers see the indicator's icons / pace
labels and the menu's headers / bars / forecast strings in one image.
The fixtures themselves document the scenario each render covers.

There is no checked-in pixel golden — the renders publish to the PR's
visual-review page via the `visual-review.json` manifest (see
devinfra/pr_visuals/plans/goldens_to_pr_visuals.md); the hard gate is
that gnome-shell boots, the extension reaches ENABLED, and every
fixture opens its menu and screenshots successfully.
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import pytest_bazel
from PIL import Image
from testcontainers.core.container import DockerContainer

from aiquota.testing.quota_fixtures import FIXTURE_NAMES, load_fixture_data
from util.bazel.runfiles import get_required_path
from util.oci import OciImage, load_oci_image
from util.testing.gnome import GnomeSession, crop_panel_menu
from util.testing.undeclared_outputs import undeclared_outputs_dir
from util.testing.visual_review import retain_review_asset

logger = logging.getLogger(__name__)


_GNOME_SHELL_TEST = OciImage("_main/gnome/test_image/gnome_shell_test.rloc", "gnome-shell-test:pinned")
_EXTENSION_ZIP = "_main/aiquota/gnome/aiquota.zip"
_EXTENSION_UUID = "aiquota@allegedly.works"

# Xvfb dims must match boot.sh — the combined panel+menu crop extends to
# the right edge, so the test driver needs to know it.

# gnome-shell ExtensionState (see js/misc/extensionUtils.js).

_TEST_DBUS_DEST = "works.allegedly.AiQuotaTest"
_TEST_DBUS_PATH = "/works/allegedly/AiQuotaTest"


def test_extension_metadata_supports_gnome_50() -> None:
    """Keep the distributed zip loadable by wyrm2's GNOME Shell generation."""
    with zipfile.ZipFile(get_required_path(_EXTENSION_ZIP)) as extension_zip:
        metadata = json.loads(extension_zip.read("metadata.json"))

    assert "50" in metadata["shell-version"]


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


@pytest.fixture(scope="module")
def fixture_json_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Materialize YAML source fixtures as JSON for the GNOME JS test hook."""
    dest = tmp_path_factory.mktemp("ai-quota-fixtures")
    for fixture_name in FIXTURE_NAMES:
        src = get_required_path(f"_main/aiquota/testing/fixtures/{fixture_name}.yaml")
        data = load_fixture_data(src)
        (dest / f"{fixture_name}.json").write_text(json.dumps(data, indent=2) + "\n")
    return dest


@pytest.fixture(scope="module")
def render_session(
    gnome_shell_test_image: str, extension_dir: Path, fixture_json_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[GnomeSession, Path]]:
    """Long-lived container + gnome-shell shared across the whole matrix.

    boot.sh starts Xvfb + a long-lived dbus session bus inside the
    container; we then launch gnome-shell once with one of the fixtures
    set as initial state (so the extension's test DBus interface is
    exported), wait for it to reach ENABLED, and yield the container
    handle + host-side output directory. Each parametrized test calls
    Reload + screenshots, leaving the shell process alone.
    """
    out_dir = tmp_path_factory.mktemp("ai-quota-renders")
    out_dir.chmod(0o777)  # gnome-shell writes the screenshot as a different uid

    container = DockerContainer(gnome_shell_test_image)
    container.with_volume_mapping(str(extension_dir), f"/usr/share/gnome-shell/extensions/{_EXTENSION_UUID}", "ro")
    container.with_volume_mapping(str(fixture_json_dir), "/fixtures", "ro")
    container.with_volume_mapping(str(out_dir), "/out", "rw")

    with container:
        session = GnomeSession(
            container.get_wrapped_container(),
            extension=_EXTENSION_UUID,
            destination=_TEST_DBUS_DEST,
            object_path=_TEST_DBUS_PATH,
        )
        try:
            session.boot()
            session.start(environment={"AI_QUOTA_FIXTURE": f"/fixtures/{FIXTURE_NAMES[0]}.json"})
            session.wait_for_paint()
        except AssertionError, TimeoutError, RuntimeError:
            session.save_log(undeclared_outputs_dir() / "startup.shell.log")
            raise
        yield session, out_dir


@pytest.fixture
def undeclared_dir() -> Path:
    out = undeclared_outputs_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_render(
    render_session: tuple[GnomeSession, Path], undeclared_dir: Path, tmp_path: Path, fixture_name: str
) -> None:
    container, container_out_dir = render_session
    out_name = f"{fixture_name}.png"
    fixture_in_container = f"/fixtures/{fixture_name}.json"
    out_in_container = f"/out/{out_name}"

    try:
        # Defensively close in case a previous test left the menu open.
        container.close_menu()
        container.reload(fixture_in_container)
        geom = container.open_menu()
        container.screenshot(out_in_container)
        container.close_menu()
    except (TimeoutError, RuntimeError) as e:
        container.save_log(undeclared_dir / f"{fixture_name}.shell.log")
        pytest.fail(f"{fixture_name}: {e}")

    full_path = container_out_dir / out_name
    assert full_path.exists(), f"scrot did not produce {full_path}"

    cropped = crop_panel_menu(Image.open(full_path), geom)
    actual_path = tmp_path / f"{fixture_name}.cropped.png"
    cropped.save(actual_path)

    # Retain the render + visual-review manifest for the PR visual-review
    # publisher (devinfra/pr_visuals/publisher.py) — the pixel-review path.
    retain_review_asset(
        actual_path, title="AI quota GNOME extension", label=fixture_name.replace("_", " "), name=out_name
    )


if __name__ == "__main__":
    pytest_bazel.main()
