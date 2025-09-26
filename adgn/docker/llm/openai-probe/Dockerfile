# Minimal image for running the OpenAI probe in continuous or batch mode
# Builds a Python runtime with only the required dependencies and runs as non-root.
#
# Build instructions:
#   cd /path/to/ducktape/adgn
#   docker build -f docker/llm/openai-probe/Dockerfile -t openai-probe:latest .
#
# Push to k3s in-cluster registry:
#   # Ensure port-forward to registry is active
#   kubectl port-forward -n registry svc/registry 5000:5000 &
#
#   # Build with registry tag
#   docker build -f docker/llm/openai-probe/Dockerfile -t localhost:5000/openai-probe:latest .
#
#   # Push to registry
#   docker push localhost:5000/openai-probe:latest
#
#   # Use in k8s deployments as:
#   #   image: registry:5000/openai-probe:latest
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

# Copy the repository and install from pyproject (build isolation)
COPY . /app
# Upgrade pip and setuptools to ensure proper src-layout support
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

USER 1000:1000

# Default entrypoint runs the probe module; k8s overrides args
ENTRYPOINT ["python", "-m", "adgn.llm.openai_utils.probe"]
