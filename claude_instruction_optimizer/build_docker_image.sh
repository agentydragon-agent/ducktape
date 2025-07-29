#!/bin/bash
# Build the enhanced Claude development Docker image
# Usage: ./build_docker_image.sh [BASE_IMAGE] [TAG]

set -e

# Parse arguments
BASE_IMAGE=${1:-"gendosu/claude-code-docker:latest"}
TAG=${2:-"claude-dev:latest"}
CACHE_DIR=".docker-cache"

echo "Building Docker image with base: $BASE_IMAGE"
echo "Output tag: $TAG"

# Build with configurable base image
docker buildx build \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    --target final \
    --cache-from type=local,src="$CACHE_DIR" \
    --cache-to type=local,dest="$CACHE_DIR",mode=max \
    -t "$TAG" \
    --load \
    .

echo "Docker image built successfully!"
echo "Image name: $TAG"
echo ""
echo "Usage examples:"
echo "  # Interactive shell"
echo "  docker run -it --rm -e ANTHROPIC_API_KEY=\"\$ANTHROPIC_API_KEY\" $TAG bash"
echo ""
echo "  # Mount current directory"
echo "  docker run -it --rm -v \$(pwd):/workspace -e ANTHROPIC_API_KEY=\"\$ANTHROPIC_API_KEY\" $TAG"