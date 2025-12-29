# Editor agent package image
# Built from repo root context: docker build -f editor_agent/runtime/Dockerfile -t adgn-editor:latest .
# Image contract: /init outputs system prompt (loaded from editor_agent_runtime package resources)

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy workspace packages
COPY mcp_utils /build/mcp_utils
COPY agent_pkg_runtime /build/agent_pkg_runtime
COPY cli_util /build/cli_util
COPY editor_agent/runtime /build/editor_agent_runtime

# Install in dependency order: pip doesn't understand [tool.uv.sources] workspace refs
RUN pip install --no-cache-dir /build/mcp_utils && \
    pip install --no-cache-dir /build/agent_pkg_runtime && \
    pip install --no-cache-dir /build/cli_util && \
    pip install --no-cache-dir /build/editor_agent_runtime

# Required: /init (image contract - runs bootstrap, outputs system prompt)
COPY editor_agent/host/src/editor_agent/definition/init /init
RUN chmod +x /init

WORKDIR /workspace

CMD ["sleep", "infinity"]
