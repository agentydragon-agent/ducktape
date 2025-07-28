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
│   ├── worktree_utils.py    # Direct git/filesystem operations
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

### 2. **Worktree Operations** (Mixed CLI/Daemon)

```
# Path Operations (Server-side)
CLI → daemon_client.resolve_path() → Unix Socket → Daemon → Path Resolution

# Create/Delete Operations (CLI direct)
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

## Future Architecture Evolution

### Phase 1: Complete Daemon Migration ✅ **Partially Complete**
Path operations moved to daemon, worktree creation/deletion still CLI-direct:

```python
# ✅ Path operations now in daemon
handle_resolve_path(daemon_client, ...) → JSON-RPC request
handle_teleport_target(daemon_client, ...) → JSON-RPC request

# 🔄 Still CLI-direct (planned for migration)
handle_create_worktree(config, name) → Direct git commands
handle_delete_worktree(config, name) → Direct git commands
```

**Benefits Achieved**:
- Server authority for path operations
- Consistent error handling for status/path ops
- Better testing isolation
- Enhanced type safety with structured responses

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

## Recent Refactoring Completed (January 2025)

Major architecture improvements completed:

### Configuration System Overhaul
- **WT_DIR-based**: Single environment variable for all configuration
- **Frozen dataclass**: Immutable Configuration with upfront validation  
- **No defaults**: All configuration fields now explicitly required
- **Clean separation**: WT_DIR for daemon/state, main_repo for git operations

### Naming and Structure Cleanup  
- **GitStatusdDaemon → WtDaemon**: Removed misleading terminology
- **GitStatusdDaemonClient → WtClient**: Consistent naming throughout
- **Dead code removal**: Deleted unused timing utilities and --verbose flag
- **Duplicate elimination**: Consolidated client initialization logic

### Error Handling Improvements
- **Error propagation**: Fixed 9+ patterns that masked errors with fallbacks
- **Structured results**: Replaced tuple returns with WorktreeGitStatus dataclass
- **Helper extraction**: Reduced code nesting in daemon handlers

### Protocol Enhancements
- **Server authority**: Moved path manipulation from client to server
- **New RPC methods**: Added worktree_resolve_path and worktree_teleport_target
- **Type safety**: Enhanced Pydantic models throughout protocol
