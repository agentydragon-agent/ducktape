#!/bin/bash
set -euo pipefail

# Build the Docker image
docker build -t llm-html:latest .

# Run the container
docker run -d --name llm-html -p 9000:9000 llm-html:latest

echo "Container started! Access at http://localhost:9000"
echo "To stop: docker stop llm-html && docker rm llm-html"
