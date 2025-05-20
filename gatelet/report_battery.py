"""Report battery status to a Gatelet server."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any, Iterable, Optional

import psutil
from httpx import AsyncClient

from .report_event import send_event


def gather_battery() -> dict[str, Any]:
    """Collect battery information."""
    try:
        info = psutil.sensors_battery()
    except FileNotFoundError:  # no battery present
        return {"available": False}
    if info is None:
        return {"available": False}
    return {
        "available": True,
        "percent": info.percent,
        "secs_left": info.secsleft,
        "plugged": info.power_plugged,
    }


async def send_battery_status(
    url: str,
    integration: str,
    token: str | None = None,
    client: Optional[AsyncClient] = None,
) -> dict[str, Any]:
    """Send battery status to Gatelet."""
    payload = gather_battery()
    return await send_event(url, integration, payload, token=token, client=client)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Send battery status to Gatelet")
    parser.add_argument("--url", required=True, help="Base URL of Gatelet server")
    parser.add_argument("--integration", required=True, help="Integration name")
    parser.add_argument("--token", help="Bearer token if required")
    args = parser.parse_args(list(argv) if argv is not None else None)

    data = asyncio.run(
        send_battery_status(args.url, args.integration, token=args.token)
    )
    print(json.dumps(data))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
