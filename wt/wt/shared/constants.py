# Main repository branch aliases
MAIN_REPO_ALIASES = {"main", "master"}

# Command names that are reserved for the CLI
COMMAND_NAMES = {"ls", "rm", "status", "cp", "path", "-c", "help"}

# All reserved names that cannot be used for worktree names
RESERVED_NAMES = MAIN_REPO_ALIASES | COMMAND_NAMES

# Display constants
MAIN_WORKTREE_DISPLAY_NAME = "main"
