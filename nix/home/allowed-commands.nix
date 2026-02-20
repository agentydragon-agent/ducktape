# Single Source of Truth for AI agent always-allowed commands
#
# Used by:
#   - nix/home/claude_code.nix (Claude Code permissions)
#   - nix/home/gemini_cli.nix (Gemini CLI policies)
#
# Commands listed here are safe for AI agents to execute without user approval.
#
# Safety criteria:
#   ✓ Read-only operations (query state, don't modify)
#   ✓ May write to build artifacts (bazel-out/, target/) but not source
#   ✓ No side effects on system state
#   ✗ Don't modify source code (git add/commit, file edits)
#   ✗ Don't modify system state (package installs, service control)
#
# Format: { type = "prefix"|"exact"; cmd = "full command string"; }
#   - type = "prefix": allows trailing arguments (e.g., "git status --short")
#   - type = "exact": no additional arguments allowed
{
  # All allowed commands (no sudo - these are user-accessible commands)
  noSudo = [
    # Git read-only operations (prefix match - allows additional flags)
    {
      type = "prefix";
      cmd = "git diff";
    }
    {
      type = "prefix";
      cmd = "git log";
    }
    {
      type = "prefix";
      cmd = "git show";
    }
    {
      type = "prefix";
      cmd = "git stash list";
    }
    {
      type = "prefix";
      cmd = "git stash show";
    }
    {
      type = "prefix";
      cmd = "git status";
    }

    # TODO: Add more git read-only commands:
    # { type = "prefix"; cmd = "git branch"; }
    # { type = "prefix"; cmd = "git remote"; }
    # { type = "prefix"; cmd = "git tag"; }
    # { type = "prefix"; cmd = "git blame"; }
    # { type = "prefix"; cmd = "git reflog"; }

    {
      type = "prefix";
      cmd = "bazel query";
    }
    {
      type = "prefix";
      cmd = "bazel cquery";
    }
    {
      type = "prefix";
      cmd = "bazel aquery";
    }
    {
      type = "prefix";
      cmd = "bazel info";
    }

    # Home manager operations
    {
      type = "prefix";
      cmd = "home-manager build";
    }
    # TODO: Add build system queries:
    # { type = "prefix"; cmd = "npm list"; }
    # { type = "prefix"; cmd = "npm outdated"; }
    # { type = "prefix"; cmd = "npm audit"; }
    # { type = "prefix"; cmd = "pip list"; }
    # { type = "prefix"; cmd = "pip show"; }
    # { type = "prefix"; cmd = "cargo tree"; }
    # { type = "prefix"; cmd = "cargo search"; }

    # TODO: Add test execution commands (safe - only writes to build artifacts):
    # { type = "exact"; cmd = "npm test"; }
    # { type = "exact"; cmd = "npm run test"; }
    # { type = "exact"; cmd = "bazel test //..."; }
    # { type = "exact"; cmd = "cargo test"; }
    # { type = "exact"; cmd = "cargo check"; }
    # { type = "exact"; cmd = "cargo clippy"; }
  ];
}
