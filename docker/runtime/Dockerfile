# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

# Minimal runtime image (shared by runtime exec and policy-eval)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/adgn

# Reuse apt metadata between builds when BuildKit is available
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt/lists \
    apt-get update \
    && apt-get install -y --no-install-recommends \
       g++ make ripgrep postgresql-client

# Copy workspace packages (dependencies first for better caching)
COPY cli_util/pyproject.toml cli_util/
COPY cli_util/src cli_util/src

COPY net_util/pyproject.toml net_util/
COPY net_util/src net_util/src

COPY openai_utils/pyproject.toml openai_utils/
COPY openai_utils/src openai_utils/src

COPY agent_core/pyproject.toml agent_core/
COPY agent_core/src agent_core/src

COPY mcp_infra/pyproject.toml mcp_infra/README.md mcp_infra/
COPY mcp_infra/src mcp_infra/src

COPY agent_runtimes/agent_container_util/pyproject.toml agent_runtimes/agent_container_util/
COPY agent_runtimes/agent_container_util/src agent_runtimes/agent_container_util/src

# Copy adgn package
COPY adgn/pyproject.toml adgn/
COPY adgn/src adgn/src

# Copy agent_server package (for policy_eval.shim)
COPY agent_server/pyproject.toml agent_server/README.md agent_server/
COPY agent_server/src agent_server/src

# Cache wheel downloads via BuildKit to speed up repeated builds
# Install packages in dependency order
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ./cli_util ./net_util ./openai_utils ./agent_core ./mcp_infra ./agent_runtimes/agent_container_util ./adgn ./agent_server

CMD ["python", "-c", "print('adgn runtime image ready')"]
