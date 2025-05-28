#!/bin/bash
set -euo pipefail

# Build the Docker image
docker build -t llm-html:latest .

# Function to cleanup on exit
cleanup() {
    echo -e "\nStopping and removing container..."
    docker rm -f llm-html 2>/dev/null || true
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Run the container interactively
echo "Starting container... Press Ctrl-C to stop"
echo "Access at http://localhost:9000"
docker run --rm --name llm-html -p 9000:9000 llm-html:latest
