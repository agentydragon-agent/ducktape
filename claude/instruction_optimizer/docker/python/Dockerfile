FROM claude-base:latest

# Install Python development environment
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install common Python packages
RUN pip3 install --no-cache-dir \
    requests \
    flask \
    fastapi \
    uvicorn \
    pytest \
    black \
    ruff \
    mypy

# Set Python as default
RUN ln -sf /usr/bin/python3 /usr/bin/python

LABEL dev.environment="python"
LABEL dev.description="Python development environment with common packages"