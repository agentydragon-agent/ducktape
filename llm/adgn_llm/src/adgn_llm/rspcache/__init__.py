"""Lightweight OpenAI Responses-compatible proxy (SQLite authoritative store).

Quick hello-world and standup instructions

1) Install dev deps and get console script (one-time):

   uv sync --extra dev

   This installs the project in editable mode and makes the `rspcache` console
   script available in your active devenv. (If you don't use `uv`, you can
   `python -m pip install -e .` in the project root.)

2) Start the proxy (in one shell):

   # set the upstream OpenAI key the proxy will use to call OpenAI
   export OPENAI_API_KEY=sk-...                # required by proxy to forward

   # start using the console script (recommended)
   rspcache --host 127.0.0.1 --port 8000

   # or run directly with uvicorn
   uvicorn adgn_llm.openai_responses_proxy:APP --host 127.0.0.1 --port 8000

3) Point a client at the proxy and fire a request (in another shell):

   # direct the OpenAI SDK to use the local proxy as the API base
   export OPENAI_API_BASE=http://127.0.0.1:8000

   # Example: non-streaming Python call
   python - <<'PY'
   import asyncio
   from openai import AsyncOpenAI

   async def main():
       client = AsyncOpenAI()
       resp = await client.responses.create(model="o4-mini", input=[{"role":"user","content":"Hello"}])
       print(resp)

   asyncio.run(main())
   PY

   # Example: streaming Python call (proxy will forward chunks as they arrive)
   python - <<'PY'
   import asyncio
   from openai import AsyncOpenAI

   async def main():
       client = AsyncOpenAI()
       maybe_iter = await client.responses.create(model="o4-mini", input=[{"role":"user","content":"Stream 1..3"}], stream=True)
       async for event in maybe_iter:
           print(event)

   asyncio.run(main())
   PY

Proxy behavior notes (important)
- The proxy uses a single SQLite DB as the authoritative store (responses + response_frames). It derives a deterministic key from the request fields only (model, input, and the explicitly-included request knobs).
- Streaming: the proxy *forwards chunks to the client immediately as upstream sends them* (it does not buffer and send only at the end). It also parses NDJSON/SSE frames and persists the parsed frames to the DB when the stream completes successfully.
- Non-streaming: the proxy forwards the request, waits for the full JSON response, and persists the summary/response in the DB.
- The proxy requires OPENAI_API_KEY in its own environment for upstream access; client-side OPENAI_API_KEY is optional when pointing at the proxy because the proxy handles upstream authentication.

Security
- Do not expose the proxy publicly without proper authentication; the DB may contain sensitive content. Protect the host with firewall or authentication in front if needed.

"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from adgn_llm.responses_db import ResponsesDB


APP = FastAPI(title="adgn-llm OpenAI Responses proxy (diskcache)")


# Upstream OpenAI Responses endpoint base
def _openai_base_url() -> str:
    # Allow overriding via OPENAI_API_BASE (common pattern)
    base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")
    return base.rstrip("/") + "/v1/responses"


def canonical_json(obj: Any) -> str:
    """Canonical, stable JSON encoding for key derivation."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def make_key_from_body(body: Dict[str, Any]) -> str:
    """Derive deterministic key for cache from body.

    Primary rule: include `model` and `input` in canonical form. Also include other
    stable request fields except known non-deterministic fields.
    """
    model = body.get("model")
    if model is None:
        raise ValueError("`model` missing from request body; required for key derivation")
    input_seq = body.get("input")
    if input_seq is None:
        # Some clients may send `input` as string; accept either
        raise ValueError("`input` missing from request body; required for key derivation")

    # Exclude fields that are normally transient or not affecting response semantics
    exclude = {"request_id", "request_timestamp", "nonce", "__meta__"}

    # Collect other kwargs sorted by key
    keyed = {k: body[k] for k in sorted(body.keys()) if k not in {"model", "input"} and k not in exclude}

    h = hashlib.sha256()
    h.update(str(model).encode("utf-8"))
    h.update(b"\n")
    h.update(canonical_json(input_seq).encode("utf-8"))
    h.update(b"\n")
    h.update(canonical_json(keyed).encode("utf-8"))
    return h.hexdigest()


@APP.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@APP.post("/v1/responses")
async def responses_endpoint(request: Request, x_cache_skip: str | None = Header(None)) -> JSONResponse:
    """OpenAI Responses-compatible endpoint (minimal compatibility).

    Accepts JSON body similar to OpenAI Responses.create(). Uses an exact-key cache.
    Supports streaming by forwarding upstream stream chunks to the client and
    capturing the full stream to store in cache after completion.
    """
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {e}")

    # allow explicit cache skip via header or payload
    header_skip = x_cache_skip in ("1", "true", "True")
    payload_skip = bool(body.get("cache_skip"))
    cache_skip = header_skip or payload_skip

    try:
        key = make_key_from_body(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
                return JSONResponse(content=summary or {}, status_code=200, headers=headers)
        finally:
            await db.close()

    # Prepare upstream call
    upstream_url = _openai_base_url()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured in env")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # If streaming requested, stream upstream and proxy chunks through while capturing
    if is_stream:

        async def stream_generator():
            # Text buffer accumulates decoded UTF-8 text across chunk boundaries
            text_buffer = ""
            frames: list[dict] = []
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream("POST", upstream_url, json=body, headers=headers) as resp:
                        if resp.status_code >= 400:
                            # read body and raise
                            t = await resp.aread()
                            raise HTTPException(
                                status_code=502,
                                detail=f"Upstream error: {t.decode(errors='ignore')} (status={resp.status_code})",
                            )

                        # iterate raw bytes and forward them to the client while parsing NDJSON/SSE-like lines
                        async for chunk in resp.aiter_bytes():
                            if not chunk:
                                continue
                            # Forward raw bytes to client immediately
                            yield chunk

                            # Maintain a UTF-8 decoded rolling buffer for line parsing
                            try:
                                chunk_text = chunk.decode("utf-8")
                            except Exception:
                                # fallback replace errors
                                chunk_text = chunk.decode("utf-8", errors="replace")
                            text_buffer += chunk_text

                            # Process complete lines; leave the last partial line in buffer
                            if "\n" in text_buffer:
                                parts = text_buffer.split("\n")
                                for line in parts[:-1]:
                                    line = line.strip()
                                    if not line:
                                        continue
                                    # SSE-style: lines may be 'data: {...}'
                                    if line.startswith("data:"):
                                        content = line[len("data:") :].lstrip()
                                    else:
                                        content = line
                                    if content == "[DONE]":
                                        # sentinel; skip storing
                                        continue
                                    try:
                                        obj = json.loads(content)
                                    except Exception:
                                        # Non-JSON frame encountered in NDJSON stream — abort
                                        raise HTTPException(
                                            status_code=502,
                                            detail=f"Non-JSON NDJSON frame: {content[:200]!r}",
                                        )
                                    frames.append(obj)
                                # last part is partial
                                text_buffer = parts[-1]

                        # After stream ends, process remaining buffer if any
                        remaining = text_buffer.strip()
                        if remaining:
                            if remaining.startswith("data:"):
                                remaining = remaining[len("data:") :].lstrip()
                            try:
                                obj = json.loads(remaining)
                                frames.append(obj)
                            except Exception:
                                # Non-JSON trailing partial — abort
                                raise HTTPException(
                                    status_code=502,
                                    detail=f"Non-JSON trailing NDJSON partial: {remaining[:200]!r}",
                                )

                except Exception as e:
                    # upstream failure during streaming
                    print(f"Upstream streaming error: {e}")
                    raise
                finally:
                    # After stream completes, store parsed frames as NDJSON list
                    try:
                        if frames:
                            from adgn_llm.responses_db import ResponsesDB

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

        # StreamResponse - return with streaming media-type for SSE/NDJSON
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"X-Cache-Hit": "0", "X-Cache-Key": key},
        )

    # Non-streaming path: forward and wait for full JSON response
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(upstream_url, json=body, headers=headers)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upstream request failed: {e}")

    try:
        resp_json = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Upstream returned non-JSON response")

    # Store into SQLite DB (authoritative single store)
    try:
        db = ResponsesDB()
        await db.init()
        try:
            # Finalize or upsert the response summary
            await db.finalize_response(key, response_obj=resp_json, summary_obj=resp_json)
        finally:
            await db.close()
    except Exception as e:
        print(f"WARNING: failed to write DB key={key}: {e}")

    headers = {"X-Cache-Hit": "0", "X-Cache-Key": key}
    return JSONResponse(content=resp_json, status_code=resp.status_code, headers=headers)
