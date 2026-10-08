"""Bounded screenshot convergence, with diagnostic frames on failure."""

import asyncio
from pathlib import Path

from playwright.async_api import Page

from util.testing.page_capture import WAIT_TIMEOUT_MS, wait_for_stable


async def stable_full_page_png(
    page: Page, *, name: str, diagnostics: Path, attempts: int = 6, timeout_ms: int = WAIT_TIMEOUT_MS
) -> bytes:
    if attempts < 2:
        raise ValueError("stability requires at least two captures")
    frames: list[bytes] = []
    try:
        async with asyncio.timeout(timeout_ms / 1000):
            for _ in range(attempts):
                await wait_for_stable(page)
                frame = await page.screenshot(full_page=True, animations="disabled", caret="hide", scale="css")
                if frames and frame == frames[-1]:
                    return frame
                frames.append(frame)
    except TimeoutError as exc:
        await asyncio.to_thread(_write_frames, diagnostics, name, frames)
        raise AssertionError(f"{name}: capture did not finish within {timeout_ms}ms; inspect {diagnostics}") from exc
    except Exception:
        await asyncio.to_thread(_write_frames, diagnostics, name, frames)
        raise
    await asyncio.to_thread(_write_frames, diagnostics, name, frames)
    raise AssertionError(f"{name}: render did not stabilize in {attempts} captures; inspect {diagnostics}")


def _write_frames(diagnostics: Path, name: str, frames: list[bytes]) -> None:
    diagnostics.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames):
        (diagnostics / f"{name}.attempt{index}.png").write_bytes(frame)
