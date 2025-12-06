# syntax=docker/dockerfile:1.7
# Properties critic base image
# - Minimal Python image with CLI tools used by runbooks
# - Exposes adgn-detectors-custom via PYTHONPATH shim over src/

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# OS tools
# Interactive inspection tools (zsh, neovim, bat) are for human use via snapshot exec
RUN --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        ripgrep \
        bash \
        zsh \
        neovim \
        bat \
        nodejs \
        npm \
        universal-ctags \
        jq \
        fd-find \
        postgresql-client \
        curl \
        golang-go

WORKDIR /opt/adgn

# Install semgrep via official installer (requires semgrep-core binary)
RUN curl -sSL https://github.com/semgrep/semgrep/releases/latest/download/semgrep-$(uname -s)-$(uname -m) -o /usr/local/bin/semgrep \
 && chmod +x /usr/local/bin/semgrep

# Copy repo sources to make adgn.* importable without installing the whole package.
COPY src /opt/adgn/src
COPY pyproject.toml /opt/adgn/

ENV PYTHONPATH="/opt/adgn/src"

# Python tools used by runbooks (install as wheels)
# MCP SDK is included for HTTP server connectivity (Phase 1: MCP over Docker network)
# Note: semgrep installed above as binary, not via pip
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip \
 && PIP_NO_CACHE_DIR=0 python -m pip install \
        pydantic \
        ruff==0.13.3 \
        mypy==1.18.2 \
        vulture==2.14 \
        bandit \
        safety \
        pip-audit \
        radon \
        xenon \
        pylint \
        lizard \
        import-linter \
        pyan3 \
        pytest \
        coverage \
        codespell \
        pyupgrade \
        refurb \
        flynt \
        pydocstyle \
        interrogate \
        diff-cover \
        mcp>=1.0.0

# Node-based tools
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm install -g pyright \
 && npm install -g jscpd

# Install mcptools via Go
ENV GOPATH=/opt/go
ENV PATH="$GOPATH/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/go-build,sharing=locked \
    --mount=type=cache,target=$GOPATH/pkg/mod,sharing=locked \
    go install github.com/f/mcptools/cmd/mcptools@latest \
 && ln -s /opt/go/bin/mcptools /usr/local/bin/mcptools

# Provide a CLI shim for our custom detectors
RUN printf '#!/usr/bin/env bash\nexec python -m adgn.props.detectors.cli_custom "$@"\n' > /usr/local/bin/adgn-detectors-custom \
 && chmod +x /usr/local/bin/adgn-detectors-custom

# Sanity checks to fail the build if tools are missing/miswired
COPY docker/llm/properties-critic/check_tools.sh /usr/local/bin/check_tools.sh
RUN chmod +x /usr/local/bin/check_tools.sh && /usr/local/bin/check_tools.sh || true

CMD ["bash", "-lc", "sleep infinity"]
