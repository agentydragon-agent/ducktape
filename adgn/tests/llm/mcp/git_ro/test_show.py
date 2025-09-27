from __future__ import annotations

import pytest

from adgn.llm.mcp.git_ro.server import (
    DiffFormat,
    ListSlice,
    ShowInput,
)


@pytest.mark.asyncio
async def test_git_show_name_status(typed_git_ro) -> None:
    async with typed_git_ro() as (client, session):
        ns_union = await client.git_show(
            ShowInput(
                object="HEAD",
                format=DiffFormat.NAME_STATUS,
                list_slice=ListSlice(offset=0, limit=100),
            )
        )
        assert ns_union.type == "name-status"
        assert ns_union.items


@pytest.mark.asyncio
async def test_git_show_stat(typed_git_ro) -> None:
    async with typed_git_ro() as (client, session):
        st_union = await client.git_show(
            ShowInput(
                object="HEAD",
                format=DiffFormat.STAT,
                list_slice=ListSlice(offset=0, limit=100),
            )
        )
        assert st_union.type == "stat"
        assert st_union.items


@pytest.mark.asyncio
async def test_git_show_patch(typed_git_ro) -> None:
    async with typed_git_ro() as (client, session):
        pt_union = await client.git_show(
            ShowInput(object="HEAD", format=DiffFormat.PATCH)
        )
        assert pt_union.type == "patch"
        assert isinstance(pt_union.body, str)
