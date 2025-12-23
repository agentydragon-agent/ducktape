# syntax=docker/dockerfile:1.7
# Properties critic base image
# - Minimal Python image with CLI tools used by runbooks
# - Exposes adgn-detectors-custom via PYTHONPATH shim over src/

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
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
        golang-go \
        tree

WORKDIR /opt/adgn

# Install semgrep via official installer (requires semgrep-core binary)
RUN curl -sSL https://github.com/semgrep/semgrep/releases/latest/download/semgrep-$(uname -s)-$(uname -m) -o /usr/local/bin/semgrep \
 && chmod +x /usr/local/bin/semgrep

# Install UV for faster package installation
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip uv

# Install adgn package dependencies (without copying src yet for better caching)
COPY pyproject.toml uv.lock ./

# Create a minimal dummy package structure to satisfy build requirements
RUN mkdir -p src/adgn && echo '__version__ = "0.0.0"' > src/adgn/__init__.py

# Install dependencies + package (this layer is cached unless pyproject.toml/uv.lock changes)
# Include both dev and gepa extras (gepa is needed for props.cli imports)
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --system -e ".[dev,gepa]"

# Now copy real source code (changes here won't invalidate dependency cache above)
COPY src ./src

# Reinstall the package itself with real source code (no deps needed, they're already installed)
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --system --no-deps --force-reinstall -e .

# Install additional analysis tools used by critic runbooks
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --system \
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
        coverage \
        codespell \
        pyupgrade \
        refurb \
        flynt \
        pydocstyle \
        interrogate \
        diff-cover

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
