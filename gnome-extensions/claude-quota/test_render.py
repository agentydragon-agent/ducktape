"""Golden render tests for the claude-quota GNOME extension panel.

A single test container (//gnome-extensions/test_image:gnome_shell_test_image)
is started once per module: boot.sh inside it brings up Xvfb, the
postinst-equivalent caches, and a long-lived dbus session bus, then
blocks. Each parametrized test launches a fresh gnome-shell inside that
container with fixture state injected via the CLAUDE_QUOTA_FIXTURE env
hook in extension.js, polls until the extension is ENABLED, screenshots
the X root via scrot, and kills the shell. Xvfb and the dbus session
survive across renders.

Per-render orchestration (start, poll, screenshot, kill) is driven from
this file rather than a bash render.sh — clearer error attribution per
step, structured pytest failures.

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

# Width (px) of the right-edge slice of the panel that we keep as the
# golden. The full Xvfb display is 1920x40 and includes the GNOME date
# menu in the centre, which renders the current real time and would make
# the golden comparison flake on every run. The claude-quota indicator
# lives at the right side of the panel, so we screenshot the whole panel
# but only diff the right-edge crop.
_PANEL_CROP_WIDTH = 250

# gnome-shell ExtensionState (see js/misc/extensionUtils.js).
_EXTENSION_STATE_ENABLED = 1

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


@pytest.fixture(scope="module")
def render_session(
    gnome_shell_test_image: str, extension_dir: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[docker.models.containers.Container, Path]]:
    """Long-lived container shared across every parametrized test in the module.

    The image's CMD is `sleep infinity`; we exec boot.sh once to start
    Xvfb + dbus and create the postinst-equivalent caches, poll for the
    /tmp/boot.ready sentinel, then yield the container handle and the
    host-side output directory. Each per-test test_panel call launches a
    fresh gnome-shell inside the same container.
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
        # Detached: boot.sh blocks on `wait $XVFB_PID`, which keeps Xvfb
        # alive for the rest of the test session.
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


def _screenshot(container: docker.models.containers.Container, out_path_in_container: str) -> None:
    r = _exec_in_session(container, f"scrot --display :99 --overwrite {shlex.quote(out_path_in_container)}")
    if r.exit_code != 0:
        stderr = (r.output[1] or b"").decode(errors="replace")
        raise RuntimeError(f"scrot exit={r.exit_code}: {stderr}")


def _kill_gnome_shell(container: docker.models.containers.Container) -> None:
    # SIGTERM first; if anything is wedged, follow up with SIGKILL after a moment.
    container.exec_run(["pkill", "-TERM", "-f", "gnome-shell"])
    time.sleep(0.5)
    container.exec_run(["pkill", "-KILL", "-f", "gnome-shell"])


def _save_shell_log(container: docker.models.containers.Container, log_path: Path) -> None:
    r = container.exec_run(["cat", "/tmp/shell.log"], demux=True)
    log_path.write_bytes((r.output[0] or b"") + (r.output[1] or b""))


@pytest.fixture
def undeclared_dir() -> Path:
    out = undeclared_outputs_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.mark.parametrize("fixture_name", _FIXTURES)
def test_panel(
    render_session: tuple[docker.models.containers.Container, Path],
    undeclared_dir: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    container, container_out_dir = render_session
    out_name = f"{fixture_name}.png"
    fixture_in_container = f"/fixtures/{fixture_name}.json"
    out_in_container = f"/out/{out_name}"
    update_golden = os.environ.get("UPDATE_GOLDEN") == "1"
    shell_log_dest = undeclared_dir / f"{fixture_name}.shell.log"

    _start_gnome_shell(container, fixture_in_container)
    try:
        _wait_for_shell_bus(container)
        _wait_for_extension_enabled(container, _EXTENSION_UUID)
        # Let the panel layout settle (icons, font load, first paint).
        time.sleep(1)
        _screenshot(container, out_in_container)
    except (TimeoutError, RuntimeError) as e:
        _save_shell_log(container, shell_log_dest)
        pytest.fail(f"{fixture_name}: {e}\nsee undeclared outputs for {shell_log_dest.name}.")
    finally:
        # Always pull shell.log so reviewers / golden-update flow can see
        # what gnome-shell loaded. Always tear down — the next fixture
        # gets a fresh gnome-shell on the same Xvfb + dbus session.
        _save_shell_log(container, shell_log_dest)
        _kill_gnome_shell(container)

    full_path = container_out_dir / out_name
    assert full_path.exists(), f"scrot did not produce {full_path}"

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
