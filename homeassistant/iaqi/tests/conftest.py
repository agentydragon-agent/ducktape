"""pytest fixtures and global test tweaks."""

from __future__ import annotations

import pathlib

import pytest

# ---------------------------------------------------------------------------
# 1.  Let *pytest-homeassistant-custom-component* bootstrap the custom
#     integration for every single test.
# ---------------------------------------------------------------------------

pytest_plugins = "pytest_homeassistant_custom_component"


# ---------------------------------------------------------------------------
# 2.  Work-around Home Assistant loader blowing up on the "editable install"
#     sentinel path that `pip` adds to *sys.path* (PEP 660).  The loader
#     assumes that every entry in *sys.path* points to a real directory and
#     tries to iterate over it.
#
#     Instead of removing the sentinel (that would break the import machinery)
#     we monkey-patch `Path.iterdir()` so that it yields no results for that
#     particular pseudo-path while leaving the behaviour for *all* real paths
#     untouched.
# ---------------------------------------------------------------------------

_SENTINEL_PREFIX = "__editable__."


_orig_iterdir = pathlib.Path.iterdir


def _safe_iterdir(self: pathlib.Path):  # type: ignore[override]
    """A replacement for *Path.iterdir()* that is tolerant of fake paths."""

    if str(self).startswith(_SENTINEL_PREFIX):
        # Return an empty iterator instead of raising *FileNotFoundError*.
        return iter(())

    return _orig_iterdir(self)


pathlib.Path.iterdir = _safe_iterdir  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 3.  Convenience autouse fixture to enable the custom component.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, hass):  # noqa: D401
    """Ensure the custom component & config dir are available for every test."""

    # Point Home Assistant towards the repository root so that the loader can
    # discover the *custom_components* folder (and therefore our integration)
    import pathlib

    hass.config.config_dir = str(pathlib.Path(__file__).resolve().parents[1])

    yield
