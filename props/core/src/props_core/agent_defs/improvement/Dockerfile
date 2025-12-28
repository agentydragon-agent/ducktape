# syntax=docker/dockerfile:1
# Improvement agent package image
# Built from the packed definition tar as context

FROM python:3.12-slim AS deps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client

# Install external Python deps (rarely change, cache separately)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    openai pydantic httpx tenacity anyio \
    fastmcp mcp \
    sqlalchemy alembic psycopg psycopg2-binary asyncpg \
    tiktoken \
    rich typer typer-di jinja2 PyYAML \
    docker aiodocker \
    structlog pyhamcrest compact-json canonicaljson \
    pygit2 plotext uvicorn

# --- Final stage ---
FROM deps AS final

# Copy build context (populated by MANIFEST)
COPY . /build/

# Install local packages only (deps already installed above)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    /build/openai_utils \
    /build/agent_pkg_runtime \
    /build/agent_core \
    /build/cli_util \
    /build/mcp_infra \
    /build/net_util \
    /build/adgn \
    /build/props

# Image contract: /init outputs system prompt, /agent.md is customizable prompt
RUN printf '#!/bin/sh\nexec props critic-dev init\n' > /init && chmod +x /init
COPY agent.md /agent.md

WORKDIR /workspace

CMD ["sleep", "infinity"]
