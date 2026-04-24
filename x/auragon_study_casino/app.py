"""Study Casino backend — event-sourced.

Serves a React PWA from `frontend/dist/` and exposes an event log:

  GET  /state              -> {state, last_event_id, etag}
  POST /events             -> body: [{type, ts_ms, payload}, ...]
                              header: If-Match: "<etag>" (optional)
                              returns 200 {state, last_event_id, etag} on success,
                                      412 if If-Match doesn't match current etag
  GET  /events?since_id=N  -> paginated raw event log for debugging/analytics

Sits behind an Authentik proxy outpost (forward-auth mode); does not
re-validate the JWT. The outpost's `X-Authentik-Username` header is logged
purely for observability — there is no per-user scoping because this is a
single-user app.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from x.auragon_study_casino.config import Settings
from x.auragon_study_casino.store import EventStore, IncomingEvent, StaleETagError

logger = logging.getLogger(__name__)


class EventIn(BaseModel):
    type: str = Field(min_length=1, max_length=64)
    ts_ms: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


def create_app(settings: Settings) -> FastAPI:
    store = EventStore(settings.data_dir / "state.db")
    frontend_dist = settings.frontend_dist_dir or (Path(__file__).parent / "frontend" / "dist")

    app = FastAPI(title="Study Casino", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/state")
    def get_state() -> Response:
        loaded = store.load()
        return _snapshot_response(loaded.state, loaded.last_event_id, loaded.etag)

    @app.post("/events")
    def post_events(
        events: list[EventIn],
        x_authentik_username: Annotated[str | None, Header()] = None,
        if_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        if not events:
            raise HTTPException(status_code=400, detail="empty event list")
        incoming = [IncomingEvent(type=e.type, ts_ms=e.ts_ms, payload=e.payload) for e in events]
        try:
            loaded = store.append(incoming, if_match=if_match)
        except StaleETagError as e:
            raise HTTPException(status_code=412, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.info(
            "events appended by user=%s count=%d types=%s",
            x_authentik_username,
            len(incoming),
            [e.type for e in incoming],
        )
        return _snapshot_response(loaded.state, loaded.last_event_id, loaded.etag)

    @app.get("/events")
    def list_events(
        since_id: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> dict[str, Any]:
        return {"events": store.list_events(since_id=since_id, limit=limit)}

    # Static frontend is mounted last so /state, /events, /healthz take
    # precedence. Unknown paths fall through to index.html so the SPA can
    # route deep links client-side.
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
    else:
        logger.warning("frontend dist dir %s not found — serving API only", frontend_dist)

    return app


def _snapshot_response(state: dict[str, Any], last_event_id: int, etag: str) -> Response:
    body = json.dumps({"state": state, "last_event_id": last_event_id, "etag": etag}, separators=(",", ":"))
    return Response(content=body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "no-store"})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", stream=sys.stderr)
    settings = Settings()
    logger.info("study casino listening on %s:%d, data_dir=%s", settings.host, settings.port, settings.data_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
