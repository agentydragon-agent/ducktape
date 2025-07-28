# `adgn-worktree` - Git Worktree Management with COW

A worktree management tool that makes switching between git worktrees feel like `git switch` while adding copy-on-write functionality for rapid prototyping.

## Features

- **Quick switching** between worktrees with relative path preservation
- **Copy-on-write operations** for duplicating worktrees with uncommitted changes  
- **Path resolution** with absolute (`/foo`) and relative (`./foo`) path support
- **Process detection** for safe worktree cleanup
- **Operation logging** with XDG-compliant data storage
- **Zsh integration** for seamless shell navigation

## Requirements

- **gitstatusd**: Must be installed and available on PATH. This binary provides fast git status queries.
- **wt package**: Must be properly installed and importable (via `pip install -e .`)
- **adgn-worktree CLI**: Must be available on PATH after package installation

**Note**: Tests explicitly check for these dependencies and will fail immediately with clear error messages if any are missing, rather than producing cryptic import or subprocess errors.

## Installation

* Install the package: `pip install -e .`
* Source `wt.sh` in your shell `.bashrc` / `.zshrc` / ...
* Reload your shell / source the same dotfile.

## Usage

### Basic Commands

```bash
# Switch to existing worktree (or offer to create)
wt feature-branch

# Explicitly create new worktree from master
wt -c new-feature

# List all worktrees
wt ls

# Remove worktree (with safety checks)
wt rm old-feature

# Remove worktree forcefully
wt rm old-feature --force
```

### GitHub PR Status

All worktree status commands automatically include GitHub pull request information via the background daemon.

### Special Destinations

```bash
# Switch to main repo
wt main
wt master
```

### Copy Operations (COW)

```bash
# Copy current worktree to new one (preserves dirty state)
wt cp experiment-v2

# Copy specific worktree to new one
wt cp feature-a feature-b
```

### Path Operations

```bash
# Get current worktree root
wt path

# Get specific worktree root
wt path feature-branch

# Get absolute path from worktree root
wt path feature-branch /src/main.py

# Get path relative to current position
wt path feature-branch ./test.py

# Get path in current worktree
wt path /config.yaml
wt path ./relative/file.py
```

## Architecture

### Client-Server Design

`wt` uses a **daemon-first architecture** to separate concerns and improve performance:

#### **CLI Client** (`cli.py`)
- Pure argument parsing and coordination  
- **Never calls GitHub APIs** - delegates to daemon
- Creates individual services (daemon_client, formatter, config)
- Passes explicit dependencies to handlers

#### **Background Daemon** (`daemon.py`)
- Handles **all GitHub API operations**
- Performs git repository status queries
- JSON-RPC server over Unix socket
- Proper daemonization with file logging
- Auto-starts when needed by client
- Renamed from GitStatusdDaemon → WtDaemon for clarity

#### **Handler Functions** (`handlers.py`)
- Pure functions with explicit dependencies
- Status operations → daemon client  
- Worktree operations → direct git commands (see Future Plans)
- No service containers or hidden dependencies

### Data Flow

```
CLI → Handler → Daemon Client → Unix Socket → Daemon → GitHub API
                     ↓              ↑
              ViewFormatter    JSON-RPC Response
                     ↓              ↓
               Console Output   WorktreeStatus + PRInfo
```

### Shell Integration

The `wt` function uses IPC via file descriptor 3:

1. **Pipe Creation**: Creates anonymous pipes for bidirectional communication
2. **Command Execution**: Python script writes shell commands to fd 3
3. **Exit Code Handling**: 
   - `0`: Success - execute commands
   - `1`: Uncontrolled error - don't execute anything  
   - `2`: Controlled error - execute commands (safe recovery)
4. **Atomic Execution**: Commands only run if the tool completed successfully

This design allows:
- **Interactive prompts** that work normally
- **Clean error handling** with proper exit codes
- **Safe navigation** away from problematic locations
- **Normal stdout/stderr** for user messages

### Future Architecture Plans

**Goal**: Move all git operations to the daemon for consistency and performance.

Currently:
- ✅ **Status operations** → daemon (GitHub API + git status)
- ❌ **Worktree create/remove** → direct CLI git commands

**Planned**:
- 🔄 **Worktree create/remove** → daemon operations
- **Benefits**: Better error handling, consistent git operations, easier testing
- **Implementation**: Extend daemon protocol with create/remove RPCs

### Copy-on-Write

Uses platform-optimized COW operations:
- **macOS**: `cp -c -R` (clonefile)
- **Linux**: `cp --reflink=auto` 
- **Fallback**: `rsync`

This enables instant duplication of entire worktrees including uncommitted changes.

### Path Preservation

When switching between worktrees, the tool:
1. Detects your current relative position
2. Tries to maintain the same path in the target worktree
3. Walks up the directory tree until it finds an existing path
4. Emits the appropriate `cd` command

### Safety Features

- **Process detection**: Uses `psutil` to check for running processes in worktree
- **Git status checks**: Prevents accidental deletion of dirty worktrees
- **Reserved name protection**: Blocks creation of worktrees with command names
- **Operation logging**: Tracks all create/remove operations for audit

### Branch Naming

- All worktrees use configurable branch naming scheme (no defaults)
- Reserved names (`ls`, `rm`, `status`, etc.) are blocked
- Special cases (`main`, `master`) teleport to main repo

## Configuration

The tool uses WT_DIR environment variable to locate configuration:

```bash
export WT_DIR=/path/to/.wt
```

Configuration file at `$WT_DIR/config.yaml` specifies:
- `main_repo`: Path to main git repository (required)
- `worktrees_dir`: Directory for worktrees (required) 
- `branch_prefix`: Prefix for worktree branches (required)
- `upstream_branch`: Default upstream branch (required)
- `github_repo`: GitHub repository identifier (required)

## Directory Structure

```
~/code/
├── repo/              # Main repository
│   └── .git/
├── worktrees/         # Worktree directory
│   ├── feature-a/
│   ├── experiment/
│   └── bugfix/
└── .wt/               # Configuration and daemon state
    ├── config.yaml
    ├── daemon.sock
    └── daemon.pid
```

## Logs and Data

- **Configuration**: `$WT_DIR/config.yaml` 
- **Daemon state**: `$WT_DIR/daemon.sock`, `$WT_DIR/daemon.pid`
- **Logs**: Daemon logs to configured location

## Examples

### Rapid Prototyping Workflow

```bash
# Start working on a feature
wt feature-work
# ... make changes, experiment ...

# Branch off current state for different approach
wt cp feature-alt
# ... now you have two copies with same starting point ...

# Switch back and forth
wt feature-work
wt feature-alt

# Clean up when done
wt rm feature-alt
```

### File Operations Between Worktrees

```bash
# Compare configs
diff $(wt path main /config.yaml) $(wt path feature /config.yaml)

# Copy files between worktrees
cp $(wt path feature-a /experiment.py) $(wt path feature-b/)

# Edit file in specific worktree
vim $(wt path feature /src/main.py)
```

### Path Resolution Examples

From `/Users/you/code/worktrees/feature/src/components`:

```bash
wt path                           # /Users/you/code/worktrees/feature
wt path /tests                    # /Users/you/code/worktrees/feature/tests  
wt path ./test.py                 # /Users/you/code/worktrees/feature/src/components/test.py
wt path main ./test.py            # /Users/you/code/repo/src/components/test.py
```

## Troubleshooting

### Alias Not Working

Ensure the alias is correctly added to `~/.zshrc` and you've reloaded your shell:

```bash
# Check if alias exists
alias wt

# Manually source if needed
source ~/.zshrc
```

### Permission Errors

If you get permission errors during COW operations, the tool will fall back to rsync automatically.

### Worktree Not Found

If a worktree directory exists but git doesn't recognize it:

```bash
cd ~/code/repo
git worktree prune
```

### Process Detection Issues

If `wt rm` incorrectly detects processes, you can force removal:

```bash
wt rm worktree-name --force
```

## Advanced Usage

The tool also works as a regular CLI without the zsh integration:

```bash
# Direct CLI usage
adgn-worktree zsh ls
adgn-worktree zsh -c new-feature  
```

This is useful for scripting or debugging the tool's behavior.
