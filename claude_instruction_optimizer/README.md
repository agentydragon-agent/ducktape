# Claude Instruction Optimizer

A sophisticated system for optimizing Claude system prompts through iterative agent rollouts, pattern analysis, and automated prompt engineering. Features advanced Docker layer optimization with generic multi-repository support and intelligent dependency resolution.

## Quick Start

### Prerequisites
- Docker (with Colima on macOS)
- Python 3.8+
- Git

### 0. Install Docker Buildx (One-time Setup)

**For macOS with Colima:**
```bash
# Create Docker CLI plugins directory
mkdir -p ~/.docker/cli-plugins

# Download and install buildx for macOS ARM64
curl -Lo ~/.docker/cli-plugins/docker-buildx https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.darwin-arm64
chmod +x ~/.docker/cli-plugins/docker-buildx

# Install as default builder
docker buildx install

# Verify installation
docker buildx version
```

**For Linux:**
```bash
# Install buildx plugin
sudo apt-get update && sudo apt-get install docker-buildx-plugin
# OR
docker buildx install
```

### 1. Build Docker Dependency Layers

```bash
# Set Colima Docker socket (if using Colima)
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock

# Build all dependency layers (system-base → packages-complete)
python3 build_dependency_layers.py
```

### 2. Initialize Database and Load Tasks

```bash
# Load all seed tasks into database with dependency tracking
python3 load_seed_tasks_enhanced.py
```

### 3. Analyze Task Dependencies

```bash
# Analyze task requirements and plan optimal Docker layers
python3 build_repo_layers.py
```

### 4. Run Optimization Loop

```bash
# Run the main optimization with specific parameters
python3 optimizer.py --mode summary --iterations 5 --rollouts-per-task 3 --tasks-per-iteration 7
```

## Architecture Overview

### Core Components

#### 1. Task Management System
- **seeds.yaml**: Task definitions with dependencies, repositories, and tool permissions
- **Database persistence**: SQLAlchemy-based storage with change detection
- **Generic dependency resolution**: Intelligent Docker layer selection

#### 2. Docker Layer Optimization
- **Multi-stage builds**: 7 optimized layers from minimal to full-stack
- **Dependency-aware resolution**: Tasks automatically get minimal required environment
- **Multi-repository support**: Git repository mounting with optimal layer sharing
- **BuildKit caching**: Persistent cache for faster rebuilds

#### 3. Agent Execution System
- **Containerized rollouts**: Each task runs in optimized Docker environment
- **Repository mounting**: `/git/repo-url/` structure with `/workspace` symlinks
- **Tool restrictions**: Per-task allowed tool lists for security
- **Result tracking**: Comprehensive logging and file integrity verification

## Task Configuration Format

Tasks in `seeds.yaml` use this comprehensive format:

```yaml
- id: rust_trading_system
  prompt: |
    Build a high-frequency trading system in Rust...
  dependencies: ["rust"]                    # Docker layer dependencies
  git_repos:                               # Repository requirements
    "git@github.com:user/repo":
      commit: "abc123"
      main: true                           # Symlinked to /workspace
  internet_needed: false                   # Network access
  allowed_tools: ["Read", "Write", "Bash"] # Tool permissions

- id: python_data_analysis
  prompt: |
    Analyze cryptocurrency data using pandas...
  dependencies: ["python-data"]            # Includes pandas, numpy, matplotlib
  git_repos: {}                           # No repositories needed
  internet_needed: false
  allowed_tools: ["Read", "Write", "Edit"]

- id: full_stack_webapp
  prompt: |
    Build React frontend with FastAPI backend...
  dependencies: ["web-dev"]               # Python + Node.js + TypeScript
  git_repos: {}
  internet_needed: true
  allowed_tools: ["Read", "Write", "Edit", "Bash"]
```

## Dependency System

### Available Dependencies

| Dependency | Docker Layer | Includes |
|------------|--------------|----------|
| `minimal` | `system-base` | Basic system tools only |
| `rust` | `runtimes` | Rust toolchain + system tools |
| `go` | `runtimes` | Go runtime + system tools |
| `python` | `python-core` | Python + core packages (requests, flask, etc.) |
| `python-dev` | `python-dev` | Python + testing tools (pytest, black, mypy) |
| `python-data` | `python-data` | Python + data science (pandas, numpy, matplotlib) |
| `python-complete` | `python-complete` | Python + all utilities |
| `node`/`javascript` | `packages-complete` | All languages + Node.js + TypeScript |
| `ruby` | `packages-complete` | All languages + Ruby gems |

### Dependency Aliases

| Alias | Expands To |
|-------|------------|
| `web-dev` | `["python-core", "node"]` |
| `data-science` | `["python-data"]` |
| `full-stack` | `["python-complete", "node", "ruby"]` |

## Docker Layer Strategy

### Layer Architecture

```
claude-dev:system-base      (90MB)  ← Basic system tools
    ↓
claude-dev:runtimes         (+200MB) ← + Rust + Go
    ↓  
claude-dev:python-core      (+150MB) ← + Python + core packages
    ↓
claude-dev:python-dev       (+100MB) ← + Development tools
    ↓
claude-dev:python-data      (+300MB) ← + Data science packages
    ↓
claude-dev:python-complete  (+80MB)  ← + Utility packages
    ↓
claude-dev:packages-complete (+120MB) ← + Node.js + Ruby
```

### Build Optimization Benefits

- **Storage efficiency**: 95% reduction vs building full image per task
- **Build speed**: Incremental builds with BuildKit cache mounts
- **Runtime performance**: Minimal images start faster
- **Resource usage**: Lower memory footprint for simple tasks

## Multi-Repository Support

### Repository Layout

```
Container filesystem:
/git/
├── git@github.com:foo/
│   └── bar/                    # Full repo at specified commit
├── git@github.com:numpy/  
│   └── numpy/                     # Additional repo at specified commit
└── ...

/workspace → /git/git@github.com:foo/bar  # Symlink for main repo
```

### Repository Build Process

1. **Base layers**: Copy full repository from local checkout
2. **Commit layers**: Incremental `git checkout` operations  
3. **Layer optimization**: Merge-base analysis minimizes total layers
4. **Automatic symlinks**: Main repository available at `/workspace`

## Commands Reference

### Development Commands

```bash
# Test dependency resolution system
python3 test_dependency_system.py

# Build specific dependency layer
docker build --target python-data -t claude-dev:python-data .

# Test task loading with validation
python3 -c "
import yaml
from dependency_manager import DependencyResolver
resolver = DependencyResolver()
print('Available dependencies:', resolver.get_available_dependencies())
"
```

### Build Commands

```bash
# Build all dependency layers with caching
DOCKER_BUILDKIT=1 ./build_dependency_layers.sh

# Build with registry cache (CI/CD)
docker buildx build \
  --cache-from type=registry,ref=registry.com/claude-dev:cache \
  --cache-to type=registry,ref=registry.com/claude-dev:cache,mode=max \
  -t claude-dev:latest \
  --push .
```

### Analysis Commands

```bash
# Analyze Docker layer usage across all tasks  
python3 build_repo_layers.py

# Show detailed task dependency breakdown
python3 -c "
from build_repo_layers import load_task_configs
from dependency_manager import DependencyResolver, TaskDependencies

configs = load_task_configs()
resolver = DependencyResolver()
deps = [TaskDependencies(dependencies=c.dependencies) for c in configs]
analysis = resolver.analyze_dependencies_across_tasks(deps)

for image, count in analysis['image_priority']:
    print(f'{image}: {count} tasks')
"
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DOCKER_HOST` | Docker socket path | `/var/run/docker.sock` |
| `DOCKER_BUILDKIT` | Enable BuildKit | `1` |
| `DATABASE_URL` | SQLite database path | `sqlite:///optimizer.db` |

## File Structure

```
.
├── seeds.yaml                    # Task definitions with dependencies
├── dependency_manager.py         # Generic dependency resolution system
├── generic_repo_manager.py       # Multi-repository Docker layer management
├── build_repo_layers.py         # Main build script and analysis
├── load_seed_tasks_enhanced.py  # Database persistence with validation
├── database.py                  # SQLAlchemy models and schema
├── optimizer.py                 # Main optimization loop
├── Dockerfile                   # Multi-stage dependency layers
├── Dockerfile.repo-base         # Repository base layer template  
├── Dockerfile.repo-commit       # Repository commit layer template
├── build_dependency_layers.sh   # Build script for all Docker layers
└── README.md                    # This file
```

## Troubleshooting

### Docker Issues

```bash
# Check Docker daemon
docker info

# For Colima users
export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock

# Clear build cache
docker builder prune -a
```

### Database Issues

```bash
# Reset database schema
rm -f optimizer.db && python3 load_seed_tasks_enhanced.py

# Check task loading
python3 -c "
from load_seed_tasks_enhanced import get_db_session
from database import SeedTask
session = get_db_session()
print(f'Loaded {session.query(SeedTask).count()} tasks')
session.close()
"
```

### Layer Build Issues

```bash
# Build layers individually to debug
docker build --target system-base -t claude-dev:system-base .
docker build --target runtimes -t claude-dev:runtimes .
# ... continue for each layer

# Check layer sizes
docker images | grep claude-dev | sort
```

## Contributing

1. Add new tasks to `seeds.yaml` with appropriate dependencies
2. Test dependency resolution with `python3 test_dependency_system.py`
3. Update database schema in `database.py` if needed
4. Run full system test with `python3 build_repo_layers.py`

## Advanced Usage

### Custom Dependency Configuration

Create `dependency_config.yaml` to customize the dependency resolution:

```yaml
layers:
  custom-ml:
    image_tag: "claude-dev:custom-ml"
    provides: ["system", "python", "tensorflow", "pytorch"]
    build_order: 8
aliases:
  ai-dev: ["python-data", "tensorflow", "pytorch"]
```

### Multi-Repository Task Example

```yaml
- id: cross_platform_analysis
  prompt: "Compare Python and Rust implementations..."
  dependencies: ["python-data", "rust"]
  git_repos:
    "git@github.com:python/cpython":
      commit: "main"
      main: true
    "git@github.com:rust-lang/rust":
      commit: "stable"  
      main: false
  internet_needed: false
  allowed_tools: ["Read", "Write", "Edit", "Bash", "Grep"]
```

This creates a container with both CPython and Rust source code available, with the agent starting in the CPython repository but having access to analyze both codebases.
