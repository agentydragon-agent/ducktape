python3 optimizer.py --mode summary --iterations 5 --rollouts-per-task 3 --tasks-per-iteration 7

# Docker Build Instructions

## One-time setup (recommended)
To avoid "legacy builder" deprecation warnings, install buildx:
```bash
docker buildx install
```

## Building the image

### Optimized build with buildx caching (recommended)
```bash
# Use the build script (includes buildx cache optimization)
./build_docker_image.sh

# Or build manually with cache
docker buildx build \
    --cache-from type=local,src=.docker-cache \
    --cache-to type=local,dest=.docker-cache,mode=max \
    -t claude-dev:latest \
    --load \
    .
```

### Alternative build methods
```bash
# Simple build (no cache optimization)
DOCKER_BUILDKIT=1 docker build -t claude-dev:latest .

# Registry cache (if you have a registry)
docker buildx build \
    --cache-from type=registry,ref=your-registry/claude-dev:cache \
    --cache-to type=registry,ref=your-registry/claude-dev:cache,mode=max \
    -t claude-dev:latest \
    --push \
    .
```

## Docker Optimization Features

This Dockerfile uses a **multi-stage build** with several optimizations for faster builds and better cache reuse:

1. **Multi-stage isolation**: Only rebuild what changed
   - `system-base`: System packages (rebuild rarely)
   - `runtimes`: Rust, Go, Node runtimes (rebuild when versions change)
   - `python-core`: Core Python packages (rebuild when core deps change)
   - `python-dev`: Development tools (rebuild when dev tools change)
   - `python-data`: Data science packages (rebuild when data deps change)
   - `python-complete`: Utility packages (rebuild when utils change)
   - `packages-complete`: Node/Ruby packages
   - `final`: Environment setup

2. **BuildKit cache mounts**: Package managers reuse downloaded files across builds
   - APT cache for system packages
   - pip cache for Python packages  
   - npm cache for Node.js packages
   - Cargo cache for Rust packages
   - RubyGems cache

3. **Buildx external cache**: Persistent cache between builds
   - Local cache stored in `.docker-cache/`
   - Registry cache option for CI/CD

4. **.dockerignore**: Excludes unnecessary files from build context

### Build isolation benefits:
- Code change → only rebuilds final stage
- New utility package → rebuilds python-complete + packages-complete + final
- New core package → rebuilds from python-core onwards
- Runtime update → rebuilds from runtimes onwards

5. **Multi-repository layer optimization**: 
   - Base repository layer (shared across all commits)
   - Commit-specific layers (minimal diffs)
   - Main repository auto-symlinked to /workspace
   - Multiple repositories available at /git/ mount points

## Usage

### Generic Multi-Repository System

The system now supports tasks that work with multiple git repositories through Docker layer optimization:

#### 1. Task Configuration
Edit `seeds.yaml` to define tasks with their repository needs:

```yaml
tasks:
  - id: my_task
    prompt: "Debug system using internal tools..."
    git_repos:
      "git@github.com:foo/bar": 
        commit: "abc123"
        main: true  # Agent starts in this repo (/workspace → /git/git@github.com:foo/bar)
      "git@github.com:numpy/numpy":
        commit: "def456"
        main: false  # Available at /git/github.com/numpy/numpy
    internet_needed: false
    allowed_tools: ["Read", "Write", "Edit", "Bash"]
```

#### 2. Build Repository Layers
```bash
# Build optimized Docker layers for all tasks
python3 build_repo_layers.py
```

This analyzes all tasks and builds minimal Docker layer sets with optimal sharing.

#### 3. Standard Build (No Repositories)
```bash
# Default build for tasks without git repositories
./build_docker_image.sh

# Custom base image
./build_docker_image.sh ubuntu:22.04 my-claude-dev:v1.0
```
