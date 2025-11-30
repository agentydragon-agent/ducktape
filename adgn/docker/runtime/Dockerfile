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

COPY pyproject.toml uv.lock ./
COPY src ./src

# Cache wheel downloads via BuildKit to speed up repeated builds
RUN --mount=type=cache,target=/root/.cache/pip pip install .

CMD ["python", "-c", "print('adgn runtime image ready')"]
