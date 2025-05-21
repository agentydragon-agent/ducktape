"""Send device events to a Gatelet server."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import httpx


async def send_event(
    url: str,
    integration: str,
    payload: dict[str, Any],
    token: str | None = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Send an event payload to Gatelet.

    Args:
        url: Base URL of Gatelet server.
        integration: Integration name.
        payload: JSON payload to send.
        token: Optional bearer token.
        client: Optional ``httpx`` client for testing.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    close_client = False
    if client is None:
        client = httpx.AsyncClient()
        close_client = True
    try:
        resp = await client.post(
            f"{url.rstrip('/')}/webhook/{integration}",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()
    finally:
        if close_client:
            await client.aclose()


def _load_payload(spec: str) -> dict[str, Any]:
    if spec.startswith("@"):
        data = Path(spec[1:]).read_text(encoding="utf-8")
    else:
        data = spec
    return json.loads(data)


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Send a device event to Gatelet")
    parser.add_argument("--url", required=True, help="Base URL of Gatelet server")
    parser.add_argument("--integration", required=True, help="Integration name")
    parser.add_argument("--token", help="Bearer token if required")
    parser.add_argument("payload", help="JSON payload or @file")
    args = parser.parse_args(list(argv) if argv is not None else None)

    payload = _load_payload(args.payload)
    data = asyncio.run(
        send_event(args.url, args.integration, payload, token=args.token)
    )
    print(json.dumps(data))


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
