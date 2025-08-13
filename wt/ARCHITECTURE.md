# Architecture Documentation

## Overview

`wt` follows a **clean client-server architecture** with explicit dependency injection and clear separation between client operations and daemon-handled services.

## Directory Structure

```
wt/
├── cli.py                   # Main CLI entry point
├── client/                  # Client-side code (no GitHub APIs)
│   ├── wt_client.py         # Unix socket communication (WtClient)
│   ├── handlers.py          # Pure handler functions
│   ├── view_formatter.py    # Display formatting
│   ├── cd_utils.py          # Shell 'cd' command emission helper
│   └── shell_utils.py       # Shell command emission
├── server/                  # Server-side code (daemon only)
│   ├── wt_server.py         # Main daemon process (WtDaemon)
│   ├── git_manager.py       # Git operations for daemon
│   ├── github_client.py     # GitHub API client
│   ├── gitstatusd_client.py # GitStatusd communication
│   ├── worktree_ids.py      # WorktreeID generation
│   └── worktree_service.py  # Business logic for daemon
└── shared/                  # Shared models and utilities
    ├── config_file.py       # Configuration file schema
    ├── configuration.py     # Resolved configuration
    ├── protocol.py          # JSON-RPC protocol definitions
    ├── constants.py         # Shared constants
    ├── error_handling.py    # Error utilities
    ├── github_models.py     # GitHub data models
    └── models.py            # Core data structures
```

## Key Architectural Principles

### **Client Never Calls GitHub APIs**
- **Strict boundary**: Client-side code cannot import GitHub interfaces
- **All GitHub operations** delegated to daemon via JSON-RPC
- **Clean separation** between local operations and remote API calls
- **Server authority**: All path manipulation logic moved to server

### **Pure Handler Functions**
- Each handler declares exactly what it needs
- Easy to test and reason about

```python
# Pure function signatures
async def handle_status(daemon_client, formatter) -> None:
async def handle_status_single(daemon_client, formatter, worktree_name: str) -> None:
def handle_create_worktree(config, name: str, from_master: bool = True) -> None:
```

## Protocol Example

```python
# Client sends status request
{
    "method": "get_status", 
    "id": "uuid-123",
    "params": {"force_refresh": false}
}

# Daemon responds with WorktreeGitStatus results
{
    "id": "uuid-123",
    "result": {
        "results": {
            "wtid:main": {"name": "main", "branch_name": "master", "ahead_count": 0, ...},
            "wtid:feature": {"name": "feature", "branch_name": "test/feature", "ahead_count": 2, ...}
        },
        "total_processing_time_ms": 150.5,
        "daemon_health": {"status": "ok"}
    }
}

# New path resolution methods
{
    "method": "worktree_resolve_path",
    "params": {
        "worktree_name": "feature",
        "path_spec": "/src/main.py",
        "current_path": "/current/working/dir"
    }
}

{
    "method": "worktree_teleport_target", 
    "params": {
        "target_name": "feature",
        "current_path": "/current/working/dir"
    }
}
```

## Data Flow

### 1. **Status Operations** (Daemon-handled)

```
CLI → handle_status() → daemon_client.get_all_worktree_status()
                            ↓
                      Unix Socket Request
                            ↓
                        Daemon Process
                            ↓
                    Git Commands + GitHub API
                            ↓
                        JSON Response
                            ↓
                    WorktreeStatus objects
                            ↓
                    ViewFormatter.render()
                            ↓
                        Console Output
```

### 2. **Worktree Operations** (Daemon authority)

```
# Path Operations (Server-side)
CLI → daemon_client.resolve_path() → Unix Socket → Daemon → Path Resolution

# Create/Delete Operations (Server-side via RPC)
CLI → handlers → WtClient → JSON-RPC → WtDaemon → WorktreeService / GitManager

# Navigation emission (Client-side only)
CLI receives resolved path from daemon and emits `cd` via client/shell_utils
```

## File Organization Logic

### `/client/` - Never Calls Remote APIs
- **daemon_client.py**: Unix socket communication only
- **handlers.py**: Business logic coordination
- **view_formatter.py**: Display formatting
- **worktree_utils.py**: Local git operations

### `/server/` - Daemon Process Only  
- **daemon.py**: Main daemon process
- **daemon_protocol.py**: JSON-RPC definitions
- **github_interface.py**: GitHub API client
- **git_repo_manager.py**: Git operations for daemon
- **worktree_service.py**: Complex business logic

### `/shared/` - Common Models
- **config.py**: Configuration loading
- **models.py**: Data structures  
- **git_interface.py**: Git command wrapper
- **github_models.py**: GitHub data types

## Error Handling Strategy

### 1. **Proper Error Propagation**
- **No error swallowing**: Eliminated 9+ error masking patterns
- **JSON-RPC errors**: Proper error responses via create_error_response
- **Explicit failures**: Let programming errors crash with clear messages

### 2. **Graceful Daemon Errors**  
- Network failures → cached responses when possible
- GitHub API errors → status without PR info
- Git command failures → proper GitError exceptions
- **WorktreeGitStatus**: Structured error information in results

### 3. **Shell Integration Safety**
- Exit code 0: Execute shell commands
- Exit code 1: Don't execute (unrecoverable error)
- Exit code 2: Execute (controlled error with recovery commands)

## Performance Considerations

### Daemon Benefits
- **Persistent process**: No Python startup overhead for repeated operations
- **Connection reuse**: GitHub API clients stay alive
- **Caching**: Status results cached between operations

### Optimization Opportunities  
- **Lazy daemon startup**: Only start when needed
- **Background refresh**: Update GitHub data proactively
- **Parallel operations**: Concurrent git status checks

## Security Boundaries

### GitHub Token Handling
- **Daemon only**: Client never accesses GitHub tokens
- **Process isolation**: Token access limited to daemon process
- **File permissions**: Daemon logs protected appropriately

### File System Operations
- **Sandboxing**: Operations limited to worktree directories
- **Path validation**: Prevent directory traversal attacks
- **Permission checks**: Validate write access before operations

## Recent Refactoring Completed (January 2025)

…

## Implementation Notes (Git worktrees)

- The daemon creates worktrees via Git CLI using:
  - `git worktree add --no-checkout <path> <branch>`
- Rationale:
  - We must support creating worktrees without incurring a full checkout for very large repositories.
  - libgit2/pygit2’s `Repository.add_worktree(name, path, ref)` performs a checkout by design and cannot emulate `--no-checkout`.
  - Post-creation deletion to mimic no-checkout is explicitly forbidden (wastes time and is unsafe).
- Hydration behavior:
  - When `hydrate_worktrees=True`, we either copy from a source worktree or perform a targeted checkout of the new branch in the worktree.
  - When `hydrate_worktrees=False`, the worktree remains skeleton-only (no working files except `.git/`).
- Tests enforce this contract (unit/integration), including sparse and empty-cone cases.
