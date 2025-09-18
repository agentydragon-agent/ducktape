import sys

import pytest
import docker


def pytest_configure(config):
    # Register custom markers to avoid PytestUnknownMarkWarning
    config.addinivalue_line(
        "markers",
        "requires_docker: test requires Docker Engine (docker.from_env().ping())",
    )
    config.addinivalue_line("markers", "macos: macOS-only test")


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip tests:
    - @pytest.mark.macos when not running on macOS
    - @pytest.mark.requires_docker when Docker Engine ping fails (or docker SDK missing)
    """
    # macOS gating
    if sys.platform != "darwin":
        skip_macos = pytest.mark.skip(reason="macOS-only test (macos marker)")
        for item in items:
            if "macos" in item.keywords:
                item.add_marker(skip_macos)

    # Docker gating (SDK is a hard dependency; only skip when ping fails)
    docker_ok = True
    try:
        docker.from_env().ping()
    except Exception:
        docker_ok = False

    if not docker_ok:
        skip_docker = pytest.mark.skip(reason="requires Docker Engine (ping failed)")
        for item in items:
            if "requires_docker" in item.keywords:
                item.add_marker(skip_docker)
