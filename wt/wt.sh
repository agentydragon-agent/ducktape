# === wt shell function ===
# Git worktree management with COW & verbose timing.
# POSIX-compatible wrapper (sh, bash, zsh).
# Source this in your shell (e.g. ~/.zshrc):
#   source ~/path/to/personal/agentydragon/wt/wt.sh
#
# Usage:
#   wt [--pr] [--verbose] [command] [args...]
#
# Options:
#   --pr       Include GitHub PR status (slower)
#   --verbose  Show detailed enumeration steps and timings
#   --help     Show help

wt() {
    # Create temporary file for command communication
    local wt_command_file=$(mktemp)
    trap 'rm -f "$wt_command_file"' EXIT
    
    # Run our Python script with fd 3 redirected to the temp file
    python -m wt.cli sh "$@" 3>"$wt_command_file"
    local wt_exit_code=$?
    
    # Execute commands on success (0) or controlled error (2)
    if [ $wt_exit_code -eq 0 ] || [ $wt_exit_code -eq 2 ]; then
        if [ -s "$wt_command_file" ]; then
            local wt_shell_commands="$(cat "$wt_command_file")"
            if [ -n "$wt_shell_commands" ]; then
                eval "$wt_shell_commands"
            fi
        fi
    fi
    
    # Clean up temp file
    rm -f "$wt_command_file"
    
    return $wt_exit_code
}
