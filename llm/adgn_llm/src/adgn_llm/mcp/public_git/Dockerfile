# Combo Git + Container MCP runtime image
# Provides a useful, offline-friendly toolbox for repo work inside the sandbox container.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/bin:/bin

# Core tools: git, bash, jq, ripgrep, fd, python, build tools for light native deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash coreutils ca-certificates curl \
      git openssh-client \
      jq ripgrep fd-find \
      python3 python3-pip build-essential \
      less vim tree file procps \
    && rm -rf /var/lib/apt/lists/*

# Provide fd under canonical name if only fdfind exists on Debian
RUN if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then \
      ln -s /usr/bin/fdfind /usr/local/bin/fd; \
    fi

# Non-root user and workspace
RUN useradd -m -u 1000 worker
WORKDIR /workspace
USER 1000:1000

# Embed this Dockerfile for MCP client introspection
RUN mkdir -p /opt/combo
COPY Dockerfile /opt/combo/Dockerfile

LABEL org.opencontainers.image.title="combo-git-container-mcp-runtime" \
      org.opencontainers.image.description="Offline-friendly toolbox (git, jq, rg, fd, python3) for MCP container sessions" \
      combo.dockerfile-path="/opt/combo/Dockerfile"

# No entrypoint; the MCP host will run `sleep infinity` and exec inside
