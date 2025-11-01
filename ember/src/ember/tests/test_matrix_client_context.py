from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ember.matrix_client import MatrixClient


@pytest.mark.asyncio
async def test_matrix_client_async_context_manager_invokes_start_and_close():
    client = MatrixClient.__new__(MatrixClient)
    start_mock = AsyncMock()
    close_mock = AsyncMock()
    setattr(client, "start", start_mock)
    setattr(client, "close", close_mock)

    async with client as returned:
        assert returned is client

    start_mock.assert_awaited_once()
    close_mock.assert_awaited_once()
