__claude_linter_preexec() {
    local cmd="$1"

    [[ -z "$cmd" ]] && return
    [[ "$cmd" =~ claude-linter ]] && return

    if ! claude-linter . >/dev/null 2>&1; then
        claude-linter . >&2
        echo "🛑 Command blocked due to Claude rule violations" >&2
        false
    fi
}

__claude_original_debug_trap=$(trap -p DEBUG | sed "s/^trap -- '\\(.*\\)' DEBUG$/\\1/")
claude_install_debug_trap() {
    if [ -n "$__claude_original_debug_trap" ]; then
        trap "__claude_linter_preexec \"\$BASH_COMMAND\" && ($__claude_original_debug_trap)" DEBUG
    else
        trap '__claude_linter_preexec "$BASH_COMMAND"' DEBUG
    fi
}

claude_linter_disable() {
    trap - DEBUG
    echo "Claude linter disabled for this session"
}

claude_linter_enable() {
    claude_install_debug_trap
    echo "Claude linter enabled"
}
