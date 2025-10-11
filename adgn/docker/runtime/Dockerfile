FROM python:3.12-slim

# Minimal runtime image (shared by runtime exec and policy-eval)
# - Installs the adgn package so code is importable inside the container

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/adgn

# System build dependencies for jsonnet and similar C/C++-backed wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       g++ make ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Copy project and install. For local builds, this assumes the repository context is used.
# Adjust as needed for your build pipeline (editable vs sdist/wheel).
COPY pyproject.toml uv.lock ./
COPY src ./src

RUN pip install --no-cache-dir .

# Default command is a no-op; containers are launched with `python -c` runner by the host.
CMD ["python", "-c", "print('adgn runtime image ready')"]
