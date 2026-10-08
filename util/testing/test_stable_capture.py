import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_bazel
from playwright.async_api import Page

from util.testing.stable_capture import stable_full_page_png


async def test_returns_only_after_two_consecutive_identical_frames(tmp_path: Path) -> None:
    page = AsyncMock(spec=Page)
    page.screenshot.side_effect = [b"before", b"settled", b"settled"]
    result = await stable_full_page_png(page, name="scene", diagnostics=tmp_path, attempts=3)
    assert result == b"settled"
    assert page.screenshot.await_count == 3
    assert not await asyncio.to_thread(lambda: list(tmp_path.iterdir()))


async def test_nonconvergence_fails_and_retains_every_frame(tmp_path: Path) -> None:
    page = AsyncMock(spec=Page)
    page.screenshot.side_effect = [b"one", b"two", b"three"]
    with pytest.raises(AssertionError, match="scene: render did not stabilize in 3 captures"):
        await stable_full_page_png(page, name="scene", diagnostics=tmp_path, attempts=3)
    assert await asyncio.to_thread(_read_frames, tmp_path) == [b"one", b"two", b"three"]


async def test_capture_deadline_retains_frames_before_a_stalled_screenshot(tmp_path: Path) -> None:
    page = AsyncMock(spec=Page)

    async def screenshot(**_: object) -> bytes:
        if page.screenshot.await_count == 1:
            return b"first frame"
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    page.screenshot.side_effect = screenshot
    with pytest.raises(AssertionError, match="scene: capture did not finish within 200ms"):
        await stable_full_page_png(page, name="scene", diagnostics=tmp_path, timeout_ms=200)
    assert _read_frames(tmp_path) == [b"first frame"]


def _read_frames(directory: Path) -> list[bytes]:
    return [path.read_bytes() for path in sorted(directory.glob("*.png"))]


if __name__ == "__main__":
    pytest_bazel.main()
