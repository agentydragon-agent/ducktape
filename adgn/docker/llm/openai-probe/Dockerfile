# Minimal image for running the OpenAI probe in continuous or batch mode
# Builds a Python runtime with only the required dependencies and runs as non-root.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create unprivileged user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy the repository and install from pyproject (build isolation)
COPY . /app
RUN pip install --no-cache-dir .

USER 1000:1000

# Default entrypoint runs the probe module; k8s overrides args
ENTRYPOINT ["python", "-m", "adgn.llm.openai_utils.probe"]
