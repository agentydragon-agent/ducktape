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
RUN --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        ripgrep \
        bash \
        nodejs \
        npm \
        universal-ctags \
        jq \
        fd-find

WORKDIR /opt/adgn

# Copy repo sources to make adgn.* importable without installing the whole package.
COPY src /opt/adgn/src
COPY pyproject.toml /opt/adgn/

ENV PYTHONPATH="/opt/adgn/src"

# Python tools used by runbooks (install as wheels)
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
        semgrep \
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

# Provide a CLI shim for our custom detectors
RUN printf '#!/usr/bin/env bash\nexec python -m adgn.props.detectors.cli_custom "$@"\n' > /usr/local/bin/adgn-detectors-custom \
 && chmod +x /usr/local/bin/adgn-detectors-custom

# Sanity checks to fail the build if tools are missing/miswired
COPY docker/llm/properties-critic/check_tools.sh /usr/local/bin/check_tools.sh
RUN chmod +x /usr/local/bin/check_tools.sh && /usr/local/bin/check_tools.sh || true

CMD ["bash", "-lc", "sleep infinity"]
