"""Bounded screenshot convergence, with diagnostic frames on failure."""

import asyncio
from pathlib import Path

from playwright.async_api import Page

from util.testing.page_capture import wait_for_stable


async def stable_full_page_png(page: Page, *, name: str, diagnostics: Path, attempts: int = 6) -> bytes:
    if attempts < 2:
        raise ValueError("stability requires at least two captures")
    frames: list[bytes] = []
    for _ in range(attempts):
        await wait_for_stable(page)
        frame = await page.screenshot(full_page=True, animations="disabled", caret="hide", scale="css")
        if frames and frame == frames[-1]:
            return frame
        frames.append(frame)
    await asyncio.to_thread(_write_frames, diagnostics, name, frames)
    raise AssertionError(f"{name}: render did not stabilize in {attempts} captures; inspect {diagnostics}")


def _write_frames(diagnostics: Path, name: str, frames: list[bytes]) -> None:
    diagnostics.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        (diagnostics / f"{name}.attempt{index}.png").write_bytes(frame)
