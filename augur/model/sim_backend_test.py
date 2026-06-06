from __future__ import annotations

import importlib
import os

import pytest_bazel

from augur.model import sim_backend


def _reload_with_env(value: str | None) -> None:
    if value is None:
        os.environ.pop("AUGUR_SIM_BACKEND", None)
    else:
        os.environ["AUGUR_SIM_BACKEND"] = value
    importlib.reload(sim_backend)


def test_default_backend_is_jax() -> None:
    original = os.environ.get("AUGUR_SIM_BACKEND")
    try:
        _reload_with_env(None)
        assert sim_backend.current_backend() is sim_backend.SimBackend.JAX
    finally:
        _reload_with_env(original)


def test_env_can_select_numpy_reference_backend() -> None:
    original = os.environ.get("AUGUR_SIM_BACKEND")
    try:
        _reload_with_env("numpy")
        assert sim_backend.current_backend() is sim_backend.SimBackend.NUMPY
    finally:
        _reload_with_env(original)


if __name__ == "__main__":
    pytest_bazel.main()
