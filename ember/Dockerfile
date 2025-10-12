# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=0

WORKDIR /opt/build

COPY pyproject.toml README.md uv.lock ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip wheel \
    && pip wheel --wheel-dir /tmp/wheels .

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/agentd

RUN python -m venv /opt/agentd/.venv

ENV PATH="/opt/agentd/.venv/bin:${PATH}"

COPY --from=builder /tmp/wheels /tmp/wheels

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install --no-index --find-links=/tmp/wheels ember \
    && rm -rf /tmp/wheels

EXPOSE 8000

ENTRYPOINT ["agentd"]
