"""Headless GNOME startup and screenshot tests for the Plaid Spend extension.

The test boots the shipped extension ZIP in a GNOME Shell session on Xvfb. It
first checks the normal startup path with the desktop daemon absent, then loads
synthetic views through a test-only D-Bus interface and captures the panel and
popup. No Plaid credentials, accounts, or live service are used.
"""

from __future__ import annotations

import ast
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
import pytest_bazel
from PIL import Image
from testcontainers.core.container import DockerContainer

from util.bazel.runfiles import get_required_path
from util.oci import OciImage, load_oci_image
from util.testing.gnome import GnomeSession, crop_panel_menu
from util.testing.undeclared_outputs import undeclared_outputs_dir
from util.testing.visual_review import retain_review_asset

_GNOME_SHELL_TEST = OciImage("_main/gnome/test_image/gnome_shell_test.rloc", "gnome-shell-test:pinned")
_EXTENSION_ZIP = "_main/finance/plaid/spend/gnome/plaid-spend-desktop.zip"
_EXTENSION_UUID = "plaid-spend@allegedly.works"
_FIXTURE_NAMES = (
    "ready_two_cards",
    "authentication_required",
    "offline",
    "allowance_paced",
    "allowance_warming",
    "allowance_exhausted",
)
_FIXTURE_DIR = "_main/finance/plaid/spend/gnome/fixtures"
_TEST_DBUS_DEST = "works.allegedly.PlaidSpendTest"
_TEST_DBUS_PATH = "/works/allegedly/PlaidSpendTest"


def test_extension_metadata_supports_gnome_50() -> None:
    """Keep the distributed ZIP loadable by the GNOME Shell version on Rugged."""
    with zipfile.ZipFile(get_required_path(_EXTENSION_ZIP)) as extension_zip:
        metadata = json.loads(extension_zip.read("metadata.json"))

    assert "50" in metadata["shell-version"]


@pytest.fixture(scope="module")
def gnome_shell_test_image() -> str:
    return load_oci_image(_GNOME_SHELL_TEST)


@pytest.fixture(scope="module")
def extension_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("plaid-spend-extension")
    with zipfile.ZipFile(get_required_path(_EXTENSION_ZIP)) as extension_zip:
        extension_zip.extractall(dest)
    return dest


@pytest.fixture(scope="module")
def fixture_json_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dest = tmp_path_factory.mktemp("plaid-spend-fixtures")
    for fixture_name in _FIXTURE_NAMES:
        source = get_required_path(f"{_FIXTURE_DIR}/{fixture_name}.json")
        (dest / f"{fixture_name}.json").write_bytes(Path(source).read_bytes())
    return dest


@pytest.fixture(scope="module")
def render_session(
    gnome_shell_test_image: str, extension_dir: Path, fixture_json_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[GnomeSession, Path]]:
    """Share one Xvfb, D-Bus bus, and GNOME Shell process across all fixtures."""
    output_dir = tmp_path_factory.mktemp("plaid-spend-renders")
    output_dir.chmod(0o777)

    container = DockerContainer(gnome_shell_test_image)
    container.with_volume_mapping(str(extension_dir), f"/usr/share/gnome-shell/extensions/{_EXTENSION_UUID}", "ro")
    container.with_volume_mapping(str(fixture_json_dir), "/fixtures", "ro")
    container.with_volume_mapping(str(output_dir), "/out", "rw")

    with container:
        session = GnomeSession(
            container.get_wrapped_container(),
            extension=_EXTENSION_UUID,
            destination=_TEST_DBUS_DEST,
            object_path=_TEST_DBUS_PATH,
        )
        try:
            session.boot()
            session.start(environment={"PLAID_SPEND_TEST": "1"})
            session.wait_for_paint()
            _assert_no_plaid_extension_error(session)
        except AssertionError, TimeoutError, RuntimeError:
            session.save_log(undeclared_outputs_dir() / "startup.shell.log")
            raise
        yield session, output_dir


def _panel_label(container: GnomeSession) -> str:
    output = container.call("GetPanelLabel").decode().strip()
    parsed = ast.literal_eval(output)
    if not isinstance(parsed, tuple) or len(parsed) != 1 or not isinstance(parsed[0], str):
        raise RuntimeError(f"GetPanelLabel returned an unexpected value: {output!r}")
    return parsed[0]


def _assert_no_plaid_extension_error(container: GnomeSession) -> None:
    log = container.log().decode(errors="replace")
    extension_error = f"/extensions/{_EXTENSION_UUID}/extension.js:"
    if extension_error in log or f"Extension {_EXTENSION_UUID}:" in log:
        raise AssertionError(f"GNOME logged a Plaid Spend extension error during default startup:\n{log}")


@pytest.mark.parametrize(
    ("fixture_name", "expected_label"),
    [
        ("ready_two_cards", "$149 !"),
        ("authentication_required", "Sign in"),
        ("offline", "Offline"),
        ("allowance_paced", "Flex $200 !"),
        ("allowance_warming", "Flex $700"),
        ("allowance_exhausted", "Flex -<$1 !!"),
    ],
)
def test_render(
    render_session: tuple[GnomeSession, Path], tmp_path: Path, fixture_name: str, expected_label: str
) -> None:
    container, output_dir = render_session
    image_name = f"{fixture_name}.png"
    fixture_path = f"/fixtures/{fixture_name}.json"
    output_path = f"/out/{image_name}"

    container.close_menu()
    container.reload(fixture_path)
    assert _panel_label(container) == expected_label
    menu_geometry = container.open_menu()
    if fixture_name.startswith("allowance_"):
        menu_text = ast.literal_eval(container.call("GetMenuText").decode().strip())[0]
        assert "Synthetic card" not in menu_text
        assert "Check a purchase / dashboard" in menu_text
        if fixture_name == "allowance_paced":
            assert "7d $28/day" in menu_text
            assert "30d $18/day" in menu_text
            assert "Leash ~$23/day" in menu_text
            assert "7d unmatched 3 ($12)" in menu_text
            assert "Sync " in menu_text
            assert "View updated" not in menu_text
            assert "sustainability target" not in menu_text
            assert "past pace is not opening debt" not in menu_text
        if fixture_name == "allowance_warming":
            assert "Pace warming up" in menu_text
            assert "7d n/a" in menu_text
        if fixture_name == "allowance_exhausted":
            assert "Exhausted" in menu_text
    container.screenshot(output_path)
    container.close_menu()

    full_path = output_dir / image_name
    assert full_path.is_file(), f"scrot did not produce {full_path}"
    actual_path = tmp_path / f"{fixture_name}.cropped.png"
    crop_panel_menu(Image.open(full_path), menu_geometry).save(actual_path)
    retain_review_asset(
        actual_path, title="Plaid Spend GNOME extension", label=fixture_name.replace("_", " "), name=image_name
    )


if __name__ == "__main__":
    pytest_bazel.main()
