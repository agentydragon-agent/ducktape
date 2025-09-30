# Minimal image for running the OpenAI probe in continuous or batch mode
# Builds a Python runtime with only the required dependencies and runs as non-root.
#
# Build instructions:
#   cd /path/to/ducktape/adgn
#   docker build -f docker/llm/openai-probe/Dockerfile -t openai-probe:latest .
#
# Push to k3s in-cluster registry (via HTTPS with Traefik):
#   # Build and tag for registry
#   docker build -f docker/llm/openai-probe/Dockerfile -t registry.k3s.local/openai-probe:latest .
#
#   # Push via HTTPS (cert-manager CA must be trusted on host)
#   docker push registry.k3s.local/openai-probe:latest
#
#   # Use in k8s deployments as:
#   #   image: registry.registry.svc.cluster.local:5000/openai-probe:latest
#
# Run examples (local):
#   docker run --rm -e OPENAI_API_KEY openai-probe:latest --help
#   docker run --rm -e OPENAI_API_KEY openai-probe:latest continuous --interval 300

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create unprivileged user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# 1) Install runtime dependencies first (cacheable) using pyproject.toml
COPY pyproject.toml /app/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    python - <<'PY'
import subprocess, tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text('utf-8'))
deps = data.get('project', {}).get('dependencies', []) or []
if deps:
    subprocess.run(['pip','install','--no-cache-dir', *deps], check=True)
PY

# 2) Copy the rest of the source and install the package without deps
COPY . /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --no-deps .

USER 1000:1000

# Default entrypoint runs the probe module; k8s overrides args
ENTRYPOINT ["python", "-m", "adgn.openai_utils.probe"]
