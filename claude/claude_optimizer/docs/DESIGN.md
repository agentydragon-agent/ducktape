# Claude Instruction Optimizer - System Design

## Architecture Overview

The Claude Instruction Optimizer uses a **per-task Docker image** approach with **runtime git repository mounting** for maximum flexibility and simplicity.

## Core Design Principles

### 🐳 **Per-Task Docker Images**
- Each task gets its own Docker image: `claude-dev:task-{task_id}`
- Images inherit from optimal base layers (python-data, rust, node, etc.)
- No shared repository layers - keeps architecture simple

### 📦 **Independent Base Layers**
- `system-base`: Ubuntu + essential tools
- `python-core`, `python-dev`, `python-data`: Python environments
- `rust`: Rust toolchain
- `node`: Node.js and npm
- `ruby`: Ruby and gems
- Each layer builds independently with optimal caching

### 🗂️ **Runtime Repository Mounting**
- Git repositories are **NOT baked into Docker images**
- Repositories cloned at runtime to `/git/{repo_url}/`
- Main repository symlinked to `/workspace` for agent execution
- Clean separation: build-time vs runtime concerns

## System Components

### Task Definition (`seeds.yaml`)
```yaml
- id: my_task
  dependencies: ["python-data"]  # Determines base Docker layer
  internet_needed: false
  allowed_tools: ["Read", "Write", "Bash"]
```

### Dependency Resolution (`dependency_manager.py`)
- Maps task dependencies → optimal Docker base layer
- Always returns per-task image name: `claude-dev:task-{task_id}`
- Generates simple Dockerfiles that inherit from base layers

### Runtime Execution (`optimizer.py`)
1. **Task Loading**: YAML → database with validation
2. **Docker Image**: Build per-task image from base layer
3. **Repository Setup**: Clone git repos at runtime
4. **Agent Execution**: Claude Code SDK in isolated container
5. **Result Collection**: Generated files, conversation logs
6. **Grading**: OpenAI o3 evaluation with structured rubrics

## Container Runtime Layout

```
/workspace/                    # Agent working directory (symlinks to main repo)
├── CLAUDE.md                 # System prompt for this task
└── ... (generated files)

/git/                         # All repositories mounted here
├── https://github.com/user/repo/     # Main repo (→ /workspace)
├── git@github.com:org/another/       # Additional repos
└── ...

/usr/bin/, /usr/lib/          # Pre-installed language runtimes
```

## Build Process

### 1. **Base Layer Build** (`build_dependency_layers.py`)
```bash
python3 -m claude_optimizer.docker.build_dependency_layers
```
- Builds independent layers in dependency order
- Uses Docker buildx with persistent caching (`.docker-cache/`)
- No git repositories involved - pure runtime environments

### 2. **Task Execution** (`optimizer.py`)
```bash
python3 -m claude_optimizer.core.optimizer --iterations 10 --rollouts-per-task 3
```
- Generates per-task Dockerfiles dynamically
- Clones git repositories at runtime
- Executes agents in isolated containers
- Collects results and grades solutions

## Key Architectural Decisions

### ✅ **Why Per-Task Images?**
- **Simplicity**: No complex shared layer optimization
- **Isolation**: Each task has dedicated environment
- **Flexibility**: Easy to customize per task in future
- **Debugging**: Clear 1:1 mapping task → image

### ✅ **Why Runtime Git Mounting?**
- **Flexibility**: Any git repository without pre-building
- **Freshness**: Always use specified commit
- **Simplicity**: No complex layer dependency graphs  
- **Development Speed**: No rebuild when changing repos

### ✅ **Why Independent Base Layers?**
- **Cache Efficiency**: Only rebuild what changed
- **Modularity**: Language runtimes evolve independently
- **Build Speed**: Parallel layer construction
- **Maintainability**: Clear layer responsibilities

## Data Flow

```
seeds.yaml → yaml_loader.py → optimizer.db
                                    ↓
dependency_manager.py → claude-dev:task-{id} (Docker image)
                                    ↓
optimizer.py → Git clone + Agent execution → Results
                                    ↓
OpenAI o3 → Grading → PromptEngineer → New system prompt
```

## Optimization Features

- **Parallel Rollouts**: Configurable concurrency (default: 8)
- **Docker Caching**: BuildKit + buildx persistent cache
- **Token Management**: Automatic file truncation for API limits
- **Cost Tracking**: Real-time cost monitoring with graceful interruption
- **Database Storage**: Complete audit trail of all executions

## Configuration Files

- `dependency_config.yaml`: Docker layer definitions
- `seeds.yaml`: Programming tasks with dependencies
- `graders_consolidated.yaml`: Evaluation rubrics
- `optimizer_config.py`: System parameters and limits

This architecture prioritizes **simplicity and maintainability** over complex optimization, while still providing excellent performance through Docker layer caching and parallel execution.
