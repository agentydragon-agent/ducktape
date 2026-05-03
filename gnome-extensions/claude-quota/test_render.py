"""Golden render tests for the claude-quota GNOME extension.

A single test container (//gnome-extensions/test_image:gnome_shell_test_image)
is started once per module: boot.sh inside it brings up Xvfb, the
postinst-equivalent caches, and a long-lived dbus session bus, then
blocks. A single gnome-shell is started inside that container (also
once per module) and the extension exports a session-bus interface
(works.allegedly.ClaudeQuotaTest, gated on CLAUDE_QUOTA_FIXTURE) that
lets this driver swap fixture state, open/close the popup menu, and
query the menu's screen geometry. Each parametrized test then just
calls Reload + screenshots — no per-fixture gnome-shell spawn.

Two views per fixture:
  - panel: right-edge crop of the top panel (icons + pace labels).
  - menu:  popup menu open, cropped to its bounding box (headers,
           summary text, time/usage bars).

Per-render orchestration (Reload, OpenMenu, GetMenuGeometry,
screenshot) is driven from this file rather than a bash render.sh —
clearer error attribution per step, structured pytest failures.

The fixture matrix exercises each branch of the renderer in
extension.js: the four pace-deviation tints (cool/ok/warn/hot), the
short-window absolute-hot override, mixed per-provider state, the
error short-circuit, and the no-data initial state.

Update flow when the rendering changes intentionally:

    bbr test //gnome-extensions/claude-quota:test_render \\
        --test_env=UPDATE_GOLDEN=1 \\
        --remote_download_outputs=toplevel --nocache_test_results

    INV=$(cat ~/.cache/bbr/last_invocation_id)
    for view in panel menu; do
      for f in both_ok both_cool both_warn both_hot \\
               short_hot mixed error no_data; do
        bbapi artifact "$INV" "${view}_${f}.png" \\
          > "gnome-extensions/claude-quota/__snapshots__/${view}_${f}.png"
      done
    done

    # Eyeball, commit, then re-run without UPDATE_GOLDEN=1 to confirm green.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import time
import zipfile
from collections.abc import Iterator
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

# Right-edge crop of the panel: where our indicator lives. The full Xvfb
# display (1920x500 — sized to fit the open popup) includes the GNOME
# date menu in the centre, which renders the current real time and would
# make the golden flake on every run.
_PANEL_CROP_WIDTH = 250
_PANEL_CROP_HEIGHT = 40

# gnome-shell ExtensionState (see js/misc/extensionUtils.js).
_EXTENSION_STATE_ENABLED = 1

_TEST_DBUS_DEST = "works.allegedly.ClaudeQuotaTest"
_TEST_DBUS_PATH = "/works/allegedly/ClaudeQuotaTest"

_FIXTURES = ["both_ok", "both_cool", "both_warn", "both_hot", "short_hot", "mixed", "error", "no_data"]
_VIEWS = ["panel", "menu"]


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
def render_session(
    gnome_shell_test_image: str, extension_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[docker.models.containers.Container, Path]]:
    """Long-lived container + gnome-shell shared across the whole matrix.

    boot.sh starts Xvfb + a long-lived dbus session bus inside the
    container; we then launch gnome-shell once with one of the fixtures
    set as initial state (so the extension's test DBus interface is
    exported), wait for it to reach ENABLED, and yield the container
    handle + host-side output directory. Each parametrized test calls
    Reload + screenshots, leaving the shell process alone.
    """
    fixtures_dir = get_required_path(f"_main/gnome-extensions/claude-quota/test_fixtures/{_FIXTURES[0]}.json").parent
    out_dir = tmp_path_factory.mktemp("claude-quota-renders")
    out_dir.chmod(0o777)  # gnome-shell writes the screenshot as a different uid

    container = DockerContainer(gnome_shell_test_image)
    container.with_volume_mapping(str(extension_dir), f"/usr/share/gnome-shell/extensions/{_EXTENSION_UUID}", "ro")
    container.with_volume_mapping(str(fixtures_dir), "/fixtures", "ro")
    container.with_volume_mapping(str(out_dir), "/out", "rw")

    with container:
        raw = container.get_wrapped_container()
        # Detached: boot.sh blocks on `wait $XVFB_PID`.
        raw.exec_run(["/usr/local/bin/boot.sh"], detach=True)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if raw.exec_run(["test", "-f", "/tmp/boot.ready"]).exit_code == 0:
                break
            time.sleep(0.2)
        else:
            xvfb_log = raw.exec_run(["cat", "/tmp/xvfb.log"], demux=True).output[0] or b""
            pytest.fail(
                f"container boot.sh never produced /tmp/boot.ready within 30s\n"
                f"xvfb.log:\n{xvfb_log.decode(errors='replace')}"
            )

        try:
            _start_gnome_shell(raw, f"/fixtures/{_FIXTURES[0]}.json")
            _wait_for_shell_bus(raw)
            _wait_for_extension_enabled(raw, _EXTENSION_UUID)
            _wait_for_test_dbus(raw)
        except (TimeoutError, RuntimeError) as e:
            _save_shell_log(raw, undeclared_outputs_dir() / "session-startup.shell.log")
            pytest.fail(f"render_session startup failed: {e}")
        yield raw, out_dir


def _exec_in_session(
    container: docker.models.containers.Container, shell_cmd: str, *, detach: bool = False
) -> docker.models.containers.ExecResult:
    """Run a shell command inside the container with the dbus session bus loaded.

    Sources /tmp/dbus.env (written by boot.sh) so child processes inherit
    DBUS_SESSION_BUS_ADDRESS and connect to the long-lived bus. Sets
    DISPLAY=:99 for the in-container Xvfb. accountsservice expects a
    system bus too — point it at the session bus so connections succeed
    even though no system services exist.
    """
    full_cmd = (
        "set -euo pipefail; "
        "source /tmp/dbus.env; "
        'export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"; '
        "export DISPLAY=:99; "
        f"{shell_cmd}"
    )
    return container.exec_run(["bash", "-c", full_cmd], demux=True, detach=detach)


def _start_gnome_shell(container: docker.models.containers.Container, fixture_path_in_container: str) -> None:
    """Launch gnome-shell in the background; subsequent polls confirm readiness."""
    cmd = (
        f"export CLAUDE_QUOTA_FIXTURE={shlex.quote(fixture_path_in_container)}; "
        "gsettings set org.gnome.shell disable-user-extensions false; "
        f"gsettings set org.gnome.shell enabled-extensions '[\"{_EXTENSION_UUID}\"]'; "
        "nohup gnome-shell --x11 >/tmp/shell.log 2>&1 &"
    )
    _exec_in_session(container, cmd, detach=True)


def _wait_for_shell_bus(container: docker.models.containers.Container, *, timeout_s: float = 60) -> None:
    """Poll until org.gnome.Shell owns its bus name."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = _exec_in_session(
            container,
            "gdbus introspect --session --dest org.gnome.Shell --object-path /org/gnome/Shell >/dev/null 2>&1",
        )
        if r.exit_code == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"gnome-shell never owned the org.gnome.Shell bus name within {timeout_s}s")


def _wait_for_extension_enabled(
    container: docker.models.containers.Container, uuid: str, *, timeout_s: float = 10
) -> None:
    """Poll GetExtensionInfo until state == ENABLED (1).

    Catches both the "extension never loaded" timeout and the "extension
    loaded but bounced to ERROR/DISABLED" case (state != 1).
    """
    deadline = time.monotonic() + timeout_s
    last_response: bytes = b""
    while time.monotonic() < deadline:
        r = _exec_in_session(
            container,
            f"gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell "
            f"--method org.gnome.Shell.Extensions.GetExtensionInfo {shlex.quote(uuid)}",
        )
        last_response = (r.output[0] or b"") + (r.output[1] or b"")
        if r.exit_code == 0 and f"'state': <{_EXTENSION_STATE_ENABLED}.0>".encode() in last_response:
            return
        time.sleep(0.25)
    raise TimeoutError(
        f"extension {uuid} never reached state={_EXTENSION_STATE_ENABLED} (ENABLED) within {timeout_s}s. "
        f"Last GetExtensionInfo response: {last_response.decode(errors='replace')!r}"
    )


def _wait_for_test_dbus(container: docker.models.containers.Container, *, timeout_s: float = 10) -> None:
    """Poll until the extension has finished exporting its test DBus name."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = _exec_in_session(
            container,
            f"gdbus introspect --session --dest {_TEST_DBUS_DEST} --object-path {_TEST_DBUS_PATH} >/dev/null 2>&1",
        )
        if r.exit_code == 0:
            return
        time.sleep(0.2)
    raise TimeoutError(f"extension test DBus interface ({_TEST_DBUS_DEST}) never became reachable within {timeout_s}s")


def _test_dbus_call(
    container: docker.models.containers.Container, method: str, *args: str
) -> docker.models.containers.ExecResult:
    arg_str = " ".join(args)
    return _exec_in_session(
        container,
        f"gdbus call --session --dest {_TEST_DBUS_DEST} "
        f"--object-path {_TEST_DBUS_PATH} "
        f"--method {_TEST_DBUS_DEST}.{method} {arg_str}",
    )


_GEOMETRY_RE = re.compile(rb"\((-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\)")


def _reload_fixture(container: docker.models.containers.Container, fixture_path_in_container: str) -> None:
    r = _test_dbus_call(container, "Reload", shlex.quote(fixture_path_in_container))
    if r.exit_code != 0:
        stderr = (r.output[1] or b"").decode(errors="replace")
        raise RuntimeError(f"Reload({fixture_path_in_container}) exit={r.exit_code}: {stderr}")
    # Let the rebuilt panel/popup actors paint before the next screenshot.
    time.sleep(0.3)


def _open_menu(container: docker.models.containers.Container) -> tuple[int, int, int, int]:
    r = _test_dbus_call(container, "OpenMenu")
    if r.exit_code != 0:
        raise RuntimeError(f"OpenMenu exit={r.exit_code}: {(r.output[1] or b'').decode(errors='replace')}")
    # Allow one frame for the menu to lay out before querying its size.
    time.sleep(0.2)
    g = _test_dbus_call(container, "GetMenuGeometry")
    if g.exit_code != 0:
        raise RuntimeError(f"GetMenuGeometry exit={g.exit_code}: {(g.output[1] or b'').decode(errors='replace')}")
    blob = (g.output[0] or b"") + (g.output[1] or b"")
    m = _GEOMETRY_RE.search(blob)
    if not m:
        raise RuntimeError(f"GetMenuGeometry returned unparseable output: {blob!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def _close_menu(container: docker.models.containers.Container) -> None:
    r = _test_dbus_call(container, "CloseMenu")
    if r.exit_code != 0:
        raise RuntimeError(f"CloseMenu exit={r.exit_code}: {(r.output[1] or b'').decode(errors='replace')}")


def _screenshot(container: docker.models.containers.Container, out_path_in_container: str) -> None:
    r = _exec_in_session(container, f"scrot --display :99 --overwrite {shlex.quote(out_path_in_container)}")
    if r.exit_code != 0:
        stderr = (r.output[1] or b"").decode(errors="replace")
        raise RuntimeError(f"scrot exit={r.exit_code}: {stderr}")


def _save_shell_log(container: docker.models.containers.Container, log_path: Path) -> None:
    r = container.exec_run(["cat", "/tmp/shell.log"], demux=True)
    log_path.write_bytes((r.output[0] or b"") + (r.output[1] or b""))


@pytest.fixture
def undeclared_dir() -> Path:
    out = undeclared_outputs_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _crop_panel(full: Image.Image) -> Image.Image:
    return full.crop((full.width - _PANEL_CROP_WIDTH, 0, full.width, _PANEL_CROP_HEIGHT))


def _crop_menu(full: Image.Image, geom: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = geom
    if w <= 0 or h <= 0:
        raise AssertionError(f"menu geometry has non-positive dim: {geom}")
    # Clamp to image bounds in case Xvfb is smaller than expected.
    right = min(x + w, full.width)
    bottom = min(y + h, full.height)
    return full.crop((max(0, x), max(0, y), right, bottom))


@pytest.mark.parametrize("view", _VIEWS)
@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_render(
    render_session: tuple[docker.models.containers.Container, Path],
    undeclared_dir: Path,
    tmp_path: Path,
    fixture_name: str,
    view: str,
) -> None:
    container, container_out_dir = render_session
    out_name = f"{view}_{fixture_name}.png"
    fixture_in_container = f"/fixtures/{fixture_name}.json"
    out_in_container = f"/out/{out_name}"
    update_golden = os.environ.get("UPDATE_GOLDEN") == "1"

    try:
        # Defensively close the menu in case a previous test left it open.
        _close_menu(container)
        _reload_fixture(container, fixture_in_container)
        geom = _open_menu(container) if view == "menu" else None
        _screenshot(container, out_in_container)
        if view == "menu":
            _close_menu(container)
    except (TimeoutError, RuntimeError) as e:
        _save_shell_log(container, undeclared_dir / f"{view}_{fixture_name}.shell.log")
        pytest.fail(f"{view}/{fixture_name}: {e}")

    full_path = container_out_dir / out_name
    assert full_path.exists(), f"scrot did not produce {full_path}"

    full = Image.open(full_path)
    cropped = _crop_panel(full) if view == "panel" else _crop_menu(full, geom)  # type: ignore[arg-type]
    actual_path = tmp_path / f"{view}_{fixture_name}.cropped.png"
    cropped.save(actual_path)

    if update_golden:
        # Skip comparison; just publish the rendered PNG so the user can
        # cp it into __snapshots__/.
        shutil.copy(actual_path, undeclared_dir / out_name)
        logger.warning("UPDATE_GOLDEN=1: wrote new golden to %s", undeclared_dir / out_name)
        return

    try:
        expected_path = get_required_path(f"_main/gnome-extensions/claude-quota/__snapshots__/{out_name}")
    except RuntimeError:
        shutil.copy(actual_path, undeclared_dir / f"{view}_{fixture_name}.actual.png")
        pytest.fail(
            f"No golden checked in for {out_name}. Re-run with --test_env=UPDATE_GOLDEN=1, "
            f"then cp the produced {out_name} from undeclared outputs into "
            f"gnome-extensions/claude-quota/__snapshots__/."
        )

    assert_png_matches_golden(actual_path, expected_path, name=f"{view}_{fixture_name}", out_dir=undeclared_dir)


if __name__ == "__main__":
    pytest_bazel.main()
