from __future__ import annotations

import pytest

from git_commit_ai.git_ro.formatting import TextSlice
from git_commit_ai.git_ro.server import CatFileInput, TextPage


async def test_cat_file_rev_path(typed_git_ro) -> None:
    """Read blob from commit tree via REV:path."""
    result = await typed_git_ro.cat_file(
        CatFileInput(
            object="HEAD:README.md",
            slice=TextSlice(offset_chars=0, max_chars=1000),
        )
    )
    assert isinstance(result, TextPage)
    assert "hello" in result.body


async def test_cat_file_index_stage0(typed_git_ro) -> None:
    """Read blob from index via :path (stage 0)."""
    result = await typed_git_ro.cat_file(
        CatFileInput(
            object=":big.txt",
            slice=TextSlice(offset_chars=0, max_chars=100),
        )
    )
    assert isinstance(result, TextPage)
    assert "line 0" in result.body


async def test_cat_file_index_explicit_stage0(typed_git_ro) -> None:
    """Read blob from index via :0:path (explicit stage 0)."""
    result = await typed_git_ro.cat_file(
        CatFileInput(
            object=":0:big.txt",
            slice=TextSlice(offset_chars=0, max_chars=100),
        )
    )
    assert isinstance(result, TextPage)
    assert "line 0" in result.body


async def test_cat_file_commit_object(typed_git_ro) -> None:
    """Read raw commit object by ref."""
    result = await typed_git_ro.cat_file(
        CatFileInput(
            object="HEAD",
            slice=TextSlice(offset_chars=0, max_chars=1000),
        )
    )
    assert isinstance(result, TextPage)
    assert "tree " in result.body
    assert "author " in result.body


async def test_cat_file_tree_object(typed_git_ro) -> None:
    """Read tree object listing."""
    result = await typed_git_ro.cat_file(
        CatFileInput(
            object="HEAD^{tree}",
            slice=TextSlice(offset_chars=0, max_chars=2000),
        )
    )
    assert isinstance(result, TextPage)
    # Tree listing has filemode, type, oid, name
    assert "blob" in result.body
    assert "README.md" in result.body


async def test_cat_file_not_found(typed_git_ro) -> None:
    """FileNotFoundError for missing path."""
    with pytest.raises(FileNotFoundError, match="Path not found"):
        await typed_git_ro.cat_file(
            CatFileInput(
                object="HEAD:nonexistent.txt",
                slice=TextSlice(offset_chars=0, max_chars=100),
            )
        )


async def test_cat_file_index_not_found(typed_git_ro) -> None:
    """FileNotFoundError for missing index entry."""
    with pytest.raises(FileNotFoundError, match="Index entry not found"):
        await typed_git_ro.cat_file(
            CatFileInput(
                object=":nonexistent.txt",
                slice=TextSlice(offset_chars=0, max_chars=100),
            )
        )
