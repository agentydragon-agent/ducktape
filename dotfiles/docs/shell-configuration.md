# Shell Configuration Guide

This document explains the shell startup file organization for this system.

## Migration Status (2025-10)

**Most shell configuration has been migrated to Nix home-manager** as of October 2025.

- **Shell configurations**: Managed declaratively in `~/code/ducktape/nix/home/home.nix`
  - Programs: `programs.bash`, `programs.zsh`, `programs.atuin`, `programs.direnv`, `programs.zoxide`, `programs.eza`
  - Shell-specific initialization: `~/code/ducktape/nix/home/shell/*.sh` (bash-init.sh, zsh-init.sh, common-init.sh)
  - Aliases: `home.shellAliases`
  - Environment variables: `home.sessionVariables`

- **What remains in dotfiles**:
  - `~/.profile` - Complex conditional PATH management and legacy integrations (CUDA, lesspipe, dotnet, pnpm, machine-specific config)
  - `~/.secret_env` - Secret environment variables (not tracked in git)

- **Nix-managed theme configuration**:
  - `nix/home/p10k.zsh` - Powerlevel10k theme configuration (deployed to ~/.p10k.zsh via home.file)

- **Removed legacy tools** (2025-10):
  - **pyenv** - Not actively used (was set to "system"), Python now managed via Nix
  - **NVM** - Not installed, Node.js now managed via Nix (nodejs_22 package)
  - **Bun** - Not installed

- **Deprecated dotfiles** (now managed by Nix):
  - `~/.bashrc` → `programs.bash` in home.nix
  - `~/.zshrc` → `programs.zsh` in home.nix
  - `~/.shellrc` → `home.shellAliases` and shell init scripts
  - `~/.zshenv` → `programs.zsh.envExtra` in home.nix
  - `~/.zprofile` → Not needed (empty)

## Quick Reference (Legacy)

| File            | Purpose                   | Status          | What Goes Here                                                              |
| --------------- | ------------------------- | --------------- | --------------------------------------------------------------------------- |
| `~/.profile`    | POSIX environment setup   | **Active**      | PATH, pyenv, CUDA, lesspipe, machine-specific config, sources ~/.secret_env |
| `~/.bashrc`     | Bash interactive config   | **Nix-managed** | Managed by programs.bash in home.nix                                        |
| `~/.zshenv`     | Zsh environment (minimal) | **Nix-managed** | Managed by programs.zsh.envExtra (skip_global_compinit)                     |
| `~/.zprofile`   | Zsh login config          | **Deprecated**  | Empty (not needed)                                                          |
| `~/.zshrc`      | Zsh interactive config    | **Nix-managed** | Managed by programs.zsh in home.nix                                         |
| `~/.shellrc`    | Interactive settings      | **Nix-managed** | Migrated to home.shellAliases and shell init scripts                        |
| `~/.secret_env` | Secret environment vars   | **Active**      | API keys, tokens (not in git)                                               |

## Loading Order

**Bold** = files we define | `→` = sourced by shell | `⇒` = sourced by our scripts

### Bash

**Login shell:**

- → `/etc/profile`
- → **`~/.profile`**
  - ⇒ **`~/.secret_env`** (if exists)

**Non-login interactive:**

- → `/etc/bash.bashrc` (Debian/Ubuntu)
- → **`~/.bashrc`**
  - ⇒ **`~/.shellrc`**
    - ⇒ **`~/.profile`**
      - ⇒ **`~/.secret_env`** (if exists)

### Zsh

- → `/etc/zsh/zshenv`
- → **`~/.zshenv`** (minimal)
- **if login:** → `/etc/zsh/zprofile`, → **`~/.zprofile`** (empty)
- **if interactive:**
  - → `/etc/zsh/zshrc`
  - → **`~/.zshrc`**
    - ⇒ **`~/.shellrc`**
      - ⇒ **`~/.profile`**
        - ⇒ **`~/.secret_env`** (if exists)
    - ⇒ **`~/.p10k.zsh`** (if exists)
- **if login:** → `/etc/zsh/zlogin`

## Key Principles

1. **`~/.profile` is the single source of truth** for environment variables and PATH
2. **No duplication** - each setting appears in exactly one file
3. **Shell-agnostic first** - prefer `~/.profile` over shell-specific files
4. **Interactive vs environment** - keep them strictly separated

## What Goes Where

### `~/.profile` (Shell-agnostic environment)

- PATH modifications (using `add_path` function)
- Environment variables (`GOPATH`, `NVM_DIR`, `BUN_INSTALL`, `MC_SKIN`, `DEFAULT_CHARSET`, `AIDER_MODEL`, `GCC_COLORS`)
- Language environments (pyenv path initialization)
- lesspipe setup
- Secret environment loading
- Sourced by both `~/.bashrc` and `~/.zshrc` for non-login shells

### `~/.bashrc` / `~/.zshrc` (Interactive shell config)

- Shell options (`shopt`, `setopt`)
- Prompt configuration
- Completion setup
- Key bindings
- History settings (including atuin)
- Color support aliases (bash only - oh-my-zsh handles for zsh)
- Colored man pages (bash only - oh-my-zsh plugin for zsh)
- Source `~/.shellrc` (which contains aliases and sources `~/.profile`)

### `~/.zshenv` (Zsh-specific environment)

- Minimal - only what MUST run for all zsh (including scripts)
- Currently just `skip_global_compinit=1` (zsh-specific setting)
- Avoid heavy operations here
- Environment variables moved to `~/.profile` for consistency

### `~/.secret_env` (Secret environment variables)

- API keys, tokens, passwords
- Not tracked in git
- Sourced by `~/.profile` if it exists
- Available to all shells through profile

### `~/.shellrc` (Shell-agnostic interactive settings)

- Sources `~/.profile` first (NOT `/etc/profile` - see note below)
- All aliases and simple functions
- Interactive-only environment variables (`LESS`, `PYTHONSTARTUP`)
- dircolors setup
- nvm and bun completions loading
- Interactive functions (like `reload-env`, `bmosh`)
- Sourced by both `~/.bashrc` and `~/.zshrc`

**Note on /etc/profile**: We don't source `/etc/profile` because:

- It's meant for login shells only
- On Debian it unconditionally resets PATH, breaking Nix and other paths
- Shell-specific rc files already handle important setup (like Nix)

## Common Issues

### SSH Sessions

- **Bash**: Automatically sources `~/.bashrc` even for non-login SSH shells (bash detects network connections)
- **Zsh**: SSH creates non-login shells that skip `~/.profile`
- That's why `~/.shellrc` sources `~/.profile` - to ensure consistent environment

### Shell-Specific Considerations

- **Bash login shells**: Don't automatically source `~/.bashrc`. If you need aliases in login shells, create `~/.bash_profile` that sources both `~/.profile` and `~/.bashrc`
- **Zsh login shells**: Both `~/.zshrc` and `~/.profile` get loaded, so environment is complete

### Special Modes & Options

- **Bash as sh**: When invoked as `sh`, bash only reads `/etc/profile` and `~/.profile` for login shells, ignoring bash-specific files
- **Non-interactive shells**: Can use `BASH_ENV` environment variable to specify a file to source
- **Zsh ZDOTDIR**: Zsh looks for user config files in `$ZDOTDIR` if set, otherwise `$HOME`
- **Disabling startup files**:
  - Bash: `--noprofile` (skip profile files), `--norc` (skip rc files)
  - Zsh: `unsetopt RCS` (disable user rc files), `unsetopt GLOBAL_RCS` (disable system rc files)

## Remarks

**PATH duplication**: Use the `add_path()` function which checks for existing entries.

## Testing Changes

```bash
# Test login shell
bash -l -c 'echo $PATH'
zsh -l -c 'echo $PATH'

# Test non-login shell (like SSH)
bash -c 'echo $PATH'
zsh -c 'echo $PATH'

# Test interactive shell
bash -i -c 'alias'
zsh -i -c 'alias'
```
