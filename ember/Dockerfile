# syntax=docker/dockerfile:1.7

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/emberd

RUN python -m venv /opt/emberd/.venv

ENV PATH="/opt/emberd/.venv/bin:${PATH}"

COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY docs ./docs

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

ENTRYPOINT ["emberd"]
