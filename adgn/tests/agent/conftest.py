"""Fixtures for adgn.mcp.editor_server tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp.client import Client
import pytest

from adgn.mcp.editor_server import EditorServer
from adgn.mcp.testing.editor_stubs import EditorServerStub


@pytest.fixture
def typed_editor_factory(tmp_path: Path):
    """Factory that yields (EditorServerStub, target_path) for an in-proc editor server."""

    @asynccontextmanager
    async def _open(initial_text: str = "x = 1\n") -> AsyncIterator[tuple[EditorServerStub, Path]]:
        target = tmp_path / "sample.py"
        target.write_text(initial_text, encoding="utf-8")

        srv = EditorServer(target)
        async with Client(srv) as session:
            stub = EditorServerStub.from_server(srv, session)
            yield stub, target

    return _open
