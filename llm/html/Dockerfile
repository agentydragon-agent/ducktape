FROM python:3.11-slim AS runtime

# Avoid buffering Python stdout/stderr
ENV PYTHONUNBUFFERED=1

# Install curl for health-check ping
RUN apt-get update -qq \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Only copy dependency manifests first to leverage Docker layer cache
COPY llm/html/requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the application code from the build context
COPY llm/html/html_server.py llm/html/token_scheme.py llm/html/index.md llm/html/style.css llm/html/base.html llm/html/verify.html llm/html/tana.md ./
# Copy coding instructions from dotfiles
COPY dotfiles/codex/instructions.md ./coding.md

EXPOSE 9000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD curl --fail http://127.0.0.1:9000/ || exit 1

CMD ["python", "html_server.py"]
