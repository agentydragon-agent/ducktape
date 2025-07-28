#!/bin/bash
# Build the enhanced Claude development Docker image

set -e

echo "Building Claude development Docker image..."
docker build -t claude-dev:latest .

echo "Docker image built successfully!"
echo "Image name: claude-dev:latest"
echo ""
echo "To test the image manually:"
echo "  docker run -it --rm -e ANTHROPIC_API_KEY=\"\$ANTHROPIC_API_KEY\" claude-dev:latest bash"
echo ""
echo "To run Claude CLI directly:"
echo "  docker run -it --rm -e ANTHROPIC_API_KEY=\"\$ANTHROPIC_API_KEY\" claude-dev:latest claude"