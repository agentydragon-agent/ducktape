from __future__ import annotations

from pathlib import Path

import pytest

from adgn.definition_builder import ensure_image_from_dockerfile

REPO_ROOT = Path(__file__).parents[
    4
]  # adgn/tests/mcp/editor_docker -> [0]editor_docker/[1]mcp/[2]tests/[3]adgn/[4]ducktape

EDITOR_DOCKERFILE = "docker/editor/Dockerfile"
EDITOR_IMAGE_TAG = "adgn-editor:test"


@pytest.fixture
async def editor_image_id(async_docker_client):
    """Build or retrieve editor agent image."""
    return await ensure_image_from_dockerfile(
        async_docker_client, repo_root=REPO_ROOT, dockerfile_path=EDITOR_DOCKERFILE, tag=EDITOR_IMAGE_TAG
    )
