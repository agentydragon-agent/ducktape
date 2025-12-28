# Editor agent package image
# Built from repo root context: docker build -f docker/editor/Dockerfile -t adgn-editor:latest .
# Image contract: /init outputs system prompt (loaded from editor_util package resources)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy workspace packages
COPY agent_pkg_runtime /build/agent_pkg_runtime
COPY agent_runtimes/editor_util /build/editor_util

# Install in dependency order: pip doesn't understand [tool.uv.sources] workspace refs
RUN pip install --no-cache-dir /build/agent_pkg_runtime && \
    pip install --no-cache-dir /build/editor_util

# Required: /init (image contract - runs bootstrap, outputs system prompt)
COPY adgn/src/adgn/mcp/editor_docker/definition/init /init
RUN chmod +x /init

WORKDIR /workspace

CMD ["sleep", "infinity"]
