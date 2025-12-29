from __future__ import annotations

from pathlib import Path

import pytest

from agent_pkg import ensure_image

REPO_ROOT = Path(__file__).parents[
    4
]  # editor_agent/host/tests/conftest.py -> [0]tests/[1]host/[2]editor_agent/[3]ducktape

EDITOR_DOCKERFILE = "docker/editor/Dockerfile"
EDITOR_IMAGE_TAG = "adgn-editor:test"


@pytest.fixture
async def editor_image_id(async_docker_client):
    """Build or retrieve editor agent image."""
    return await ensure_image(async_docker_client, REPO_ROOT, EDITOR_IMAGE_TAG, dockerfile=EDITOR_DOCKERFILE)
