#!/usr/bin/env python3
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from .extract_dataset_ccr import process_file as process_ccr_file


TRACE_DIR = Path.home() / ".claude-code-router" / "logs"
OUTPUT_PATH = Path(__file__).parent / "data" / "dataset.jsonl"


def list_trace_files() -> list[Path]:
    if not TRACE_DIR.exists():
        return []
    return [p for p in sorted(TRACE_DIR.glob("trace.*")) if p.is_file()]


async def main():
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = list_trace_files()
    sem = asyncio.Semaphore(16)

    async def wrapped(p: Path):
        async with sem:
            return await process_ccr_file(p)

    results: list[list[dict]] = await asyncio.gather(*[wrapped(p) for p in files])
    count = 0
    with OUTPUT_PATH.open("w", encoding="utf-8") as out:
        for batch in results:
            for dp in batch:
                out.write(json.dumps(dp, ensure_ascii=False) + "\n")
                count += 1
    print(
        json.dumps({"event": "dataset_written", "count": count, "path": str(OUTPUT_PATH)}),
    )


if __name__ == "__main__":
    asyncio.run(main())
