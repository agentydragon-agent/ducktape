"""FastAPI application for props dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from props_backend.routes import stats

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    yield


def create_app(*, static_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        static_dir: Optional path to static files directory for frontend assets.
    """
    app = FastAPI(
        title="Props Dashboard",
        description="Training and evaluation metrics dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for development (Vite dev server on different port)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(stats.router, prefix="/api/stats", tags=["stats"])

    # Health check
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Mount static files if directory provided
    if static_dir and static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


# Default app instance for uvicorn
app = create_app()
