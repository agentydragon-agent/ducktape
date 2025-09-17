"""Lightweight OpenAI Responses-compatible proxy (SQLite authoritative store).

# Hello-world and standup instructions

## Start the proxy (in one shell):

export OPENAI_API_KEY=sk-...
rspcache --host 127.0.0.1 --port 8000   # start using the console script

# or run directly with uvicorn
uvicorn adgn.rspcache:APP --host 127.0.0.1 --port 8000

## Point a client at the proxy and fire a request (in another shell):

# direct the OpenAI SDK to use the local proxy as the API base
export OPENAI_API_BASE=http://127.0.0.1:8000

### Example: non-streaming Python call

>> import asyncio
>> from openai import AsyncOpenAI
>> client = AsyncOpenAI()
>> asyncio.run(client.responses.create(
>>     model="o4-mini",
>>     input=[{"role":"user","content":"Hello"}],
>> ))

### Example: streaming Python call (proxy will forward chunks as they arrive)

>> async def main():
>>    client = AsyncOpenAI()
>>    maybe_iter = await client.responses.create(
>>        model="o4-mini",
>>        input=[{"role":"user","content":"Stream 1..3"}],
>>        stream=True,
>>    )
>>    async for event in maybe_iter:
>>        print(event)
>>
>> asyncio.run(main())

## Proxy behavior notes (important)
- Uses SQLite as store (responses + response_frames). Derives deterministic key from request fields
  (model, input, explicitly-included knobs).
- Streaming: proxy forwards chunks to client immediately as upstream sends them
  (does not buffer and send only at the end).
- NDJSON/SSE frames are parsed and persisted in DB once stream completes successfully.
- Non-streaming: proxy forwards request, waits for full JSON response, then persists in DB.
- Proxy requires OPENAI_API_KEY in environment to talk to backend; API key is not needed to talk to frontend.

## Security
- Do not expose publicly without proper auth; DB may contain sensitive content.
- Protect host with firewall or auth if needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import hashlib
import json
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx

from adgn.rspcache.responses_db import ResponsesDB

HTTP_ERROR_MIN = 400

APP = FastAPI(title="adgn-llm OpenAI Responses proxy (diskcache)")


# Upstream OpenAI Responses endpoint base
def _openai_base_url() -> str:
    # Allow overriding via OPENAI_API_BASE (common pattern)
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")
    return base.rstrip("/") + "/v1/responses"


def canonical_json(obj: Any) -> str:
    """Canonical, stable JSON encoding for key derivation."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def make_key_from_body(body: dict[str, Any]) -> str:
    """Derive deterministic key for cache from body.

    Primary rule: include `model` and `input` in canonical form. Also include other
    stable request fields except known non-deterministic fields.
    """
    # Collect non-transient args, including model, input
    keyed = {
        k: body[k]
        for k in sorted(body.keys())
        # Exclude fields that are normally transient or not affecting response semantics
        if k not in {"request_id", "request_timestamp", "nonce", "__meta__"}
    }

    h = hashlib.sha256()
    h.update(canonical_json(keyed).encode("utf-8"))
    return h.hexdigest()


SSE_PREFIX = "data:"


def _process_complete_lines(text_buffer: str, frames: list[dict]) -> str:
    """Process complete newline-delimited lines from text_buffer and append JSON frames.

    Returns the trailing partial line (may be empty).
    """
    if "\n" not in text_buffer:
        return text_buffer
    parts = text_buffer.split("\n")
    for part in parts[:-1]:
        line = part.strip()
        if not line:
            continue
        content = (
            line[len(SSE_PREFIX) :].lstrip() if line.startswith(SSE_PREFIX) else line
        )
        if content == "[DONE]":
            # Sentinel; skip storing
            continue
        try:
            obj = json.loads(content)
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Non-JSON NDJSON frame: {content[:200]!r}",
            ) from e
        frames.append(obj)
    return parts[-1]


def _append_remaining_buffer(remaining: str, frames: list[dict]) -> None:
    """Append the final trailing buffer as a JSON frame if present."""
    remaining = remaining.strip()
    if not remaining:
        return
    if remaining.startswith(SSE_PREFIX):
        remaining = remaining[len(SSE_PREFIX) :].lstrip()
    try:
        obj = json.loads(remaining)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Non-JSON trailing NDJSON partial: {remaining[:200]!r}",
        ) from e
    frames.append(obj)


async def _proxy_stream(
    upstream_url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    key: str,
) -> AsyncIterator[bytes]:
    """Proxy upstream streaming response, yielding raw bytes and persisting frames."""
    text_buffer = ""
    frames: list[dict] = []
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            async with client.stream(
                "POST", upstream_url, json=body, headers=headers
            ) as resp:
                if resp.status_code >= HTTP_ERROR_MIN:
                    t = await resp.aread()
                    raise HTTPException(
                        status_code=502,
                        detail=f"Upstream error: {t.decode(errors='ignore')} (status={resp.status_code})",
                    )
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    yield chunk
                    text_buffer += chunk.decode("utf-8")
                    text_buffer = _process_complete_lines(text_buffer, frames)
            _append_remaining_buffer(text_buffer, frames)
        finally:
            try:
                if frames:
                    db = ResponsesDB()
                    await db.init()
                    try:
                        await db.finalize_response(
                            key,
                            response_obj=None,
                            summary_obj={"ndjson_frames": frames},
                        )
                    finally:
                        await db.close()
            except Exception:
                print(f"WARNING: failed to write DB entry key={key} after streaming")


@APP.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@APP.post("/v1/responses")
async def responses_endpoint(
    request: Request,
    x_cache_skip: str | None = Header(None),
) -> Response:
    """Minimal OpenAI Responses API-compatible endpoint

    Accepts JSON body similar to OpenAI Responses.create(). Uses an exact-key cache.
    Supports streaming by forwarding upstream stream chunks to the client and
    capturing the full stream to store in cache after completion.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}") from e

    # allow explicit cache skip via header or payload
    header_skip = x_cache_skip in ("1", "true", "True")
    payload_skip = bool(body.get("cache_skip"))
    cache_skip = header_skip or payload_skip

    try:
        key = make_key_from_body(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Cache lookup (only for non-streaming; for streaming we still check to possibly short-circuit)
    is_stream = bool(body.get("stream"))
    if not cache_skip:
        db = ResponsesDB()
        await db.init()
        try:
            status = await db.get_status(key)
            if status == "complete":
                summary = await db.get_complete_response(key)
                headers = {"X-Cache-Hit": "1", "X-Cache-Key": key}
                return JSONResponse(
                    content=summary or {},
                    status_code=200,
                    headers=headers,
                )
        finally:
            await db.close()

    # Prepare upstream call
    upstream_url = _openai_base_url()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY not configured in env",
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # If streaming requested, stream upstream and proxy chunks through while capturing
    if is_stream:
        return StreamingResponse(
            _proxy_stream(upstream_url, headers, body, key),
            media_type="text/event-stream",
            headers={"X-Cache-Hit": "0", "X-Cache-Key": key},
        )

    # Non-streaming path: forward and wait for full JSON response
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(upstream_url, json=body, headers=headers)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Upstream request failed: {e}"
            ) from e

    try:
        resp_json = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail="Upstream returned non-JSON response",
        ) from e

    # Store into SQLite DB (authoritative single store)
    try:
        db = ResponsesDB()
        await db.init()
        try:
            # Finalize or upsert the response summary
            await db.finalize_response(
                key,
                response_obj=resp_json,
                summary_obj=resp_json,
            )
        finally:
            await db.close()
    except Exception as e:
        print(f"WARNING: failed to write DB key={key}: {e}")

    headers = {"X-Cache-Hit": "0", "X-Cache-Key": key}
    return JSONResponse(
        content=resp_json,
        status_code=resp.status_code,
        headers=headers,
    )
