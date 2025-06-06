#!/bin/bash
# Development deployment script for llm_html service
# Deploys the current working tree (including uncommitted changes) to production

set -euo pipefail

# Configuration
VPS_HOST="root@agentydragon.com"  # Assumes SSH config has this host configured
REMOTE_BUILD_DIR="/tmp/llm-html-build"
CONTAINER_NAME="llm_html"  # Same as production container
IMAGE_NAME="llm-html:dev"
HOST_PORT="9000"  # Same port as production

echo "🚀 Starting deployment of current working tree to production..."

# Run unit tests first
echo "🧪 Running unit tests..."
if ! python -m pytest test_*.py -v; then
    echo "❌ Unit tests failed! Aborting deployment."
    echo "Fix the failing tests before deploying."
    exit 1
fi
echo "✅ All tests passed!"

echo "⚠️  WARNING: This will replace the production container at llm.agentydragon.com"
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Create a tarball of the current working directory
echo "📦 Creating archive of current working tree..."
# Include all necessary files (tracked, staged, and untracked)
tar -czf /tmp/llm-html-dev.tar.gz \
    --exclude=__pycache__ \
    --exclude=.pytest_cache \
    --exclude=*.pyc \
    --exclude=.git \
    *.py *.md *.html *.css *.txt *.sh Dockerfile requirements.txt

# Copy the tarball to VPS
echo "📤 Copying files to VPS..."
scp /tmp/llm-html-dev.tar.gz $VPS_HOST:$REMOTE_BUILD_DIR.tar.gz

# Clean up local tarball
rm -f /tmp/llm-html-dev.tar.gz

# Build and deploy on VPS
echo "🔨 Building and deploying on VPS..."
ssh $VPS_HOST << 'EOF'
set -euo pipefail

# Try to get existing TOKEN_SECRET from running container
SECRET=$(docker inspect llm_html 2>/dev/null | jq -r '.[0].Config.Env[] | select(startswith("TOKEN_SECRET=")) | split("=")[1]' || echo "")
if [ -z "$SECRET" ]; then
    echo "⚠️  No existing TOKEN_SECRET found, generating new one..."
    SECRET=$(openssl rand -hex 32)
fi

# Extract files
echo "📂 Extracting files..."
rm -rf /tmp/llm-html-build
mkdir -p /tmp/llm-html-build
cd /tmp/llm-html-build
tar -xzf ../llm-html-build.tar.gz

# Build Docker image
echo "🐳 Building Docker image..."
docker build -t llm-html:dev .

# Stop and remove existing container
echo "🛑 Stopping existing production container..."
docker stop llm_html 2>/dev/null || true
docker rm llm_html 2>/dev/null || true

# Run new container with production settings
echo "🚀 Starting new container..."
docker run -d \
  --name llm_html \
  --restart unless-stopped \
  -p 9000:9000 \
  -e TOKEN_SECRET="$SECRET" \
  -e SITE_URL="http://llm.agentydragon.com" \
  llm-html:dev

# Clean up
echo "🧹 Cleaning up..."
rm -rf /tmp/llm-html-build /tmp/llm-html-build.tar.gz

echo "✅ Deployment complete!"
EOF

echo "
✨ Deployment finished!

Your current working tree is now live at: http://llm.agentydragon.com

To check logs: ssh vps 'docker logs -f ${CONTAINER_NAME}'
To rollback to git version: cd ../../ansible && ansible-playbook vps.yaml --tags llm-html
"
