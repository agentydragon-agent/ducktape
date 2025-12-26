# syntax=docker/dockerfile:1
# Critic-based detector agent definition image
# Built from the packed definition tar as context

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System dependencies for code analysis
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    postgresql-client

# Install Python analysis tools
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ruff mypy vulture==2.14

# Copy build context (populated by MANIFEST)
COPY . /build/

# Install packages in dependency order
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    /build/openai_utils \
    /build/agent_runtimes/agent_container_util \
    /build/agent_core \
    /build/cli_util \
    /build/mcp_infra \
    /build/net_util \
    /build/adgn \
    /build/props

# Image contract: /init outputs system prompt, /agent.md is customizable prompt
RUN printf '#!/bin/sh\nexec props critic-agent init /agent.md\n' > /init && chmod +x /init
COPY agent.md /agent.md

WORKDIR /workspace

CMD ["sleep", "infinity"]
