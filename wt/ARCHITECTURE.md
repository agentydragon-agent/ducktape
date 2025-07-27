# Architecture Documentation

## Overview

`wt` follows a **clean client-server architecture** with explicit dependency injection and clear separation between client operations and daemon-handled services.

## Directory Structure

```
wt/
├── cli.py                   # Main CLI entry point
├── client/                  # Client-side code (no GitHub APIs)
│   ├── daemon_client.py     # Unix socket communication with daemon
│   ├── handlers.py          # Pure handler functions
│   ├── view_formatter.py    # Display formatting
│   └── worktree_utils.py    # Direct git/filesystem operations
├── server/                  # Server-side code (daemon only)
│   ├── daemon.py            # Main daemon process
│   ├── git_repo_manager.py  # Git operations for daemon
│   ├── github_interface.py  # GitHub API client
│   └── worktree_service.py  # Business logic for daemon
└── shared/                  # Shared models and utilities
    ├── config.py            # Configuration management
    ├── daemon_protocol.py    # JSON-RPC protocol definitions (shared)
    ├── git_interface.py     # Git command wrapper
    ├── github_models.py     # GitHub data models
    └── models.py            # Core data structures
```

## Key Architectural Principles

### **Client Never Calls GitHub APIs**
- **Strict boundary**: Client-side code cannot import GitHub interfaces
- **All GitHub operations** delegated to daemon via JSON-RPC
- **Clean separation** between local operations and remote API calls

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
# Client sends
{
    "method": "get_all_worktree_status", 
    "id": "uuid-123",
    "params": {}
}

# Daemon responds  
{
    "id": "uuid-123",
    "result": {
        "worktrees": {
            "main": {"branch": "master", "ahead": 0, "pr_info": {...}},
            "feature": {"branch": "adgn/feature", "ahead": 2, "pr_info": {...}}
        }
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

### 2. **Worktree Operations** (Direct CLI - Future: Daemon)

```
CLI → handle_create_worktree() → worktree_utils.create_worktree()
                                        ↓
                                Direct Git Commands
                                        ↓
                                File System Operations
                                        ↓
                                emit_cd_command()
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

### 1. **Fail Fast in Client**
- Let programming errors crash
- Only catch expected conditions (file not found, network issues)

### 2. **Graceful Daemon Errors**  
- Network failures → cached responses when possible
- GitHub API errors → status without PR info
- Git command failures → error status in response

### 3. **Shell Integration Safety**
- Exit code 0: Execute shell commands
- Exit code 1: Don't execute (unrecoverable error)
- Exit code 2: Execute (controlled error with recovery commands)

## Future Architecture Evolution

### Phase 1: Complete Daemon Migration
Move remaining git operations to daemon:

```python
# Current CLI-direct operations
handle_create_worktree(config, name) → Direct git commands

# Target daemon operations  
handle_create_worktree(daemon_client, name) → JSON-RPC request
```

**Benefits**:
- Consistent error handling
- Better testing isolation
- Centralized git operation logic

### Phase 2: Enhanced GitHub Refresh
- **File Watcher Integration**: Watch `.git` directory for changes
- **Debounced Updates**: 5-second debounce for rapid git operations  
- **Periodic Refresh**: 1-minute intervals to catch external changes
- **Smart Caching**: Proactive cache updates, always-fresh data

### Phase 3: Enhanced Daemon Features  
- **Batch Operations**: Multiple worktree operations in single request
- **Advanced GitHub Integration**: PR creation, branch management
- **Persistent Cache**: Status cache survives daemon restarts

### Phase 3: Multi-Repository Support
- **Repository Discovery**: Automatic detection of git repositories
- **Workspace Management**: Coordinate multiple repos
- **Cross-Repository Operations**: Copy files between different repos

## Testing Strategy

### Unit Testing
- **Pure functions**: Easy to test handlers individually  
- **Mock daemon**: Test client without real daemon
- **Isolated components**: Test git operations separately

### Integration Testing
- **Real daemon**: Test full client-daemon communication
- **File system**: Test actual git operations
- **GitHub API**: Test with real API (rate-limited)

### End-to-End Testing
- **Shell integration**: Test complete zsh workflow
- **Error scenarios**: Test various failure modes
- **Performance**: Measure daemon startup and response times

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

This architecture enables clean separation of concerns while maintaining performance and reliability.
