# adgn-llm Properties Critic/Linter image
# Includes Python + Node-based QA tools and vim

ARG PYTHON_VERSION=3.12-slim
FROM python:${PYTHON_VERSION}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# OS deps: git, curl, build tools, node+npm for pyright/jscpd, and vim
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential nodejs npm vim \
 && rm -rf /var/lib/apt/lists/*

# Upgrade pip toolchain
RUN python -m pip install --upgrade pip setuptools wheel

# Python QA tools
RUN pip install \
    ruff \
    mypy \
    vulture \
    bandit \
    pip-audit \
    safety \
    codespell \
    pyupgrade \
    refurb \
    flynt \
    pydocstyle \
    interrogate \
    import-linter \
    semgrep \
    radon \
    xenon \
    pylint \
    lizard \
    coverage \
    diff-cover

# Node-based tools (canonical sources)
RUN npm install -g pyright jscpd

# Quick versions sanity check (non-fatal for tools lacking --version)
RUN set -eux; \
    python --version; \
    pip --version; \
    ruff --version; \
    mypy --version; \
    pyright --version; \
    vulture --version; \
    bandit --version; \
    pip-audit --version || true; \
    safety --version; \
    codespell --version; \
    pyupgrade --version || true; \
    refurb --version || true; \
    flynt --version || true; \
    pydocstyle --version || true; \
    interrogate --version || true; \
    lint-imports --help >/dev/null 2>&1 || true; \
    semgrep --version; \
    radon --version; \
    xenon --version || true; \
    pylint --version; \
    lizard --version; \
    coverage --version; \
    diff-cover --version; \
    jscpd --version; \
    vim --version | head -1

WORKDIR /workspace
CMD ["sleep", "infinity"]
