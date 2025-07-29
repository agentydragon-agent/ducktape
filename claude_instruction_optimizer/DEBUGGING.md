# Containerized Claude Debugging Guide

This document contains critical debugging knowledge for containerized Claude execution. **Preserve this file** - these lessons will save hours when things inevitably break.

## Table of Contents

1. [Critical Issue #1: Docker buildx context isolation](#critical-issue-1-docker-buildx-context-isolation)
2. [Critical Issue #2: Containers running as root](#critical-issue-2-containers-running-as-root)
3. [Critical Issue #3: AWS Bedrock authentication in containers](#critical-issue-3-aws-bedrock-authentication-in-containers)
4. [Critical Issue #4: File exclusion for grader](#critical-issue-4-file-exclusion-for-grader)
5. [Debugging Commands](#debugging-commands)
6. [Common Failure Modes](#common-failure-modes)

---

## Critical Issue #1: Docker buildx context isolation

**Status**: RESOLVED  
**Files**: `build_dependency_layers.py:315-343`

### Problem

Task images failed to build because buildx maintains its own container-based registry separate from the host Docker daemon. When buildx exports images back to host with `--load`, subsequent builds can't find those base images.

### Symptoms

- Base layers build successfully with buildx + caching
- Task images fail with "image not found" errors  
- Error: `failed to solve: base-image:tag: not found`
- Works locally but fails in CI/automated builds

### Root Cause

Docker buildx uses a different context/registry than legacy Docker builder:
- Base images built with buildx exist in buildx context
- Subsequent builds (even with buildx) can't see these images
- Buildx tries Docker Hub first, not local registry

### Solution

**Use hybrid approach**:
- **Base layers**: Use buildx with caching (`claude-builder` with `docker-container` driver)
- **Task images**: Use legacy Docker builder (`DOCKER_BUILDKIT=0`) for local image access

### Implementation

```python
# In build_dependency_layers.py
env = os.environ.copy()
env['DOCKER_BUILDKIT'] = '0'  # Force legacy builder for task images

process = subprocess.Popen(
    build_cmd, 
    env=env,  # Pass environment with DOCKER_BUILDKIT=0
    # ... other args
)
```

### Debugging Commands

```bash
# Show host registry (what legacy builder sees)
docker images

# Show buildx registry 
docker buildx imagetools inspect <image>

# Show available builders and contexts
docker buildx ls

# Inspect builder details
docker buildx inspect claude-builder
```

---

## Critical Issue #2: Containers running as root

**Status**: RESOLVED  
**Files**: `build_dependency_layers.py:299-300`

### Problem

Containers ran as root despite `USER 1000` directive in base Dockerfile. Claude Code security restrictions require non-root execution.

### Symptoms

- Container starts but Claude Code fails with permission errors
- Need `--dangerously-skip-permissions` flag (security risk)
- Authentication setup fails due to file permissions
- Files created with root ownership

### Root Cause

Docker requires `USER` directive at the **final image stage**. Even if base Dockerfile has `USER 1000`, derived images can override this unless explicitly set.

### Solution

Add `USER 1000` directive to **task-specific Dockerfiles** in addition to base image USER directive.

### Implementation

```dockerfile
# In generated task Dockerfile
FROM base-image

# ... task-specific setup ...

# CRITICAL: Ensure container runs as non-root user
USER 1000
```

### Verification Commands

```bash
# Check user in running container
docker exec -it <container_id> whoami
# Should output: claude (or user ID 1000)

# Check file ownership
docker exec -it <container_id> ls -la /workspace
# Files should be owned by user 1000, not root
```

---

## Critical Issue #3: AWS Bedrock authentication in containers

**Status**: RESOLVED  
**Files**: `openai/scripts/bedrock_setup.sh`

### Problem

Claude Code needs AWS credentials for Bedrock but containers lack authentication setup and credential processes.

### Symptoms

- Claude fails to authenticate with Bedrock
- Missing AWS config and credential processes
- Permission errors when installing authentication scripts
- `AWS credentials not found` errors

### Root Cause

Containers start isolated without:
- AWS configuration from host
- Credential processes (adgn-aws-azure-creds)
- Proper PATH configuration for Claude Code

### Solution

Pre-task setup script (`bedrock_setup.sh`) that runs **before every task**:

1. **Copy AWS config** from host `~/.aws/config`
2. **Install credential process** in user-writable location (`/workspace/.local/bin`)
3. **Configure Claude settings** with proper PATH and environment
4. **Place everything** in `/workspace` where user 1000 has write access

### Implementation

```bash
# Key parts of bedrock_setup.sh

# Copy AWS config from host
docker cp ~/.aws/config "$CONTAINER_ID:/workspace/.aws/config"

# Install credential process in user-writable location
docker exec "$CONTAINER_ID" mkdir -p /workspace/.local/bin
docker cp ~/code/openai/personal/agentydragon/adgn_utils/adgn_utils/aws_azure_creds.py \
  "$CONTAINER_ID:/workspace/.local/bin/adgn-aws-azure-creds"
docker exec "$CONTAINER_ID" chmod +x /workspace/.local/bin/adgn-aws-azure-creds

# Configure Claude settings with proper PATH
cat > /workspace/.claude/settings.json << 'EOF'
{
  "CLAUDE_CODE_USE_BEDROCK": "1",
  "env": {
    "PATH": "/workspace/.local/bin:/usr/local/bin:/usr/bin:/bin",
    "AWS_REGION": "us-east-1"
  }
}
EOF
```

### Debugging Commands

```bash
# Check authentication setup
docker exec -it <container_id> ls -la /workspace/.claude/
docker exec -it <container_id> ls -la /workspace/.aws/
docker exec -it <container_id> ls -la /workspace/.local/bin/

# Test credential process
docker exec -it <container_id> which adgn-aws-azure-creds
docker exec -it <container_id> /workspace/.local/bin/adgn-aws-azure-creds

# Test Claude settings
docker exec -it <container_id> cat /workspace/.claude/settings.json
```

---

## Critical Issue #4: File exclusion for grader

**Status**: RESOLVED  
**Files**: `config.yaml`, `task_claude.py:_should_exclude_file()`

### Problem

Authentication directories (`.claude/`, `.local/`, `.aws/`) being passed to grader when collecting output files, causing grading errors.

### Symptoms

- Grader receives authentication files it shouldn't see
- Grading failures due to unexpected file content
- Security concern: credentials passed to grader

### Solution

Add exclusion patterns to `config.yaml` to skip authentication directories when copying files from container to host for grading.

### Implementation

```yaml
# In config.yaml
exclude_patterns:
  # ... existing patterns ...
  - "**/.claude/**"
  - "**/.local/**" 
  - "**/.aws/**"
```

The exclusion logic in `task_claude.py:_should_exclude_file()` matches these patterns against file paths during collection.

---

## Debugging Commands

### Container Investigation

```bash
# Basic container info
docker ps                                 # List running containers
docker logs <container_id>               # View container logs
docker exec -it <container_id> bash      # Interactive shell in container

# User and permissions
docker exec -it <container_id> whoami    # Check current user
docker exec -it <container_id> id        # Check user ID and groups
docker exec -it <container_id> ls -la /workspace  # Check file permissions

# Environment and configuration
docker exec -it <container_id> env       # Check environment variables
docker exec -it <container_id> echo $PATH  # Check PATH variable
docker exec -it <container_id> which claude  # Find Claude binary
```

### Authentication Debugging

```bash
# AWS configuration
docker exec -it <container_id> ls -la /workspace/.aws/
docker exec -it <container_id> cat /workspace/.aws/config

# Claude settings
docker exec -it <container_id> ls -la /workspace/.claude/
docker exec -it <container_id> cat /workspace/.claude/settings.json

# Credential process
docker exec -it <container_id> which adgn-aws-azure-creds
docker exec -it <container_id> ls -la /workspace/.local/bin/
docker exec -it <container_id> /workspace/.local/bin/adgn-aws-azure-creds
```

### Docker Image Debugging

```bash
# Image investigation
docker images                            # List available images
docker history <image_tag>               # Show image layers
docker inspect <image_tag>               # Detailed image info

# Buildx debugging
docker buildx ls                         # List builders
docker buildx inspect claude-builder     # Builder details
docker buildx imagetools inspect <image> # Image in buildx registry
```

### File System Debugging

```bash
# Container file system
docker exec -it <container_id> find /workspace -type f     # List all files
docker exec -it <container_id> du -sh /workspace/*         # Directory sizes
docker exec -it <container_id> mount                       # Show mounts

# Volume debugging
docker volume ls                         # List volumes
docker volume inspect claude_shared_git # Volume details
```

---

## Common Failure Modes

### Container Startup Issues

**Symptoms**: Container exits immediately or fails to start
```bash
# Check container status and logs
docker ps -a | grep <container_id>
docker logs <container_id>

# Common causes:
# - Base image not available
# - Volume mount errors
# - Permission issues
# - Resource constraints
```

**Fix**: Check Docker logs and ensure base images exist

### Authentication Failures

**Symptoms**: `AWS credentials not found`, `Permission denied` errors
```bash
# Check authentication setup
docker exec -it <container_id> ls -la /workspace/.aws/
docker exec -it <container_id> which adgn-aws-azure-creds
docker exec -it <container_id> cat /workspace/.claude/settings.json
```

**Fix**: Re-run bedrock_setup.sh or check script execution logs

### Permission Errors

**Symptoms**: `Operation not permitted`, files owned by root
```bash
# Check user and file ownership
docker exec -it <container_id> whoami
docker exec -it <container_id> ls -la /workspace/
```

**Fix**: Ensure task Dockerfile includes `USER 1000`

### Build Failures

**Symptoms**: `image not found`, `failed to solve` errors during image builds
```bash
# Check available images
docker images | grep claude-dev

# Check builder context
docker buildx inspect claude-builder
```

**Fix**: Use correct builder for base vs task images (see Issue #1)

---

## Emergency Debugging

When everything is broken and you need to investigate:

1. **Leave containers running** - Setup failures intentionally leave containers running for debugging
2. **Check the logs** - Always start with `docker logs <container_id>`
3. **Interactive shell** - Use `docker exec -it <container_id> bash` to explore
4. **Check recent changes** - What changed since last working state?
5. **Verify basics** - User, PATH, file permissions, mounts
6. **Test components** - Authentication, image builds, container startup separately

**Remember**: Document any new issues you discover in this file!