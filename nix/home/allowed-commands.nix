# Single Source of Truth for AI agent always-allowed commands
#
# Used by:
#   - nix/home/claude_code/default.nix (Claude Code permissions)
#   - nix/home/codex/execpolicy-rules.nix (Codex execpolicy)
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
let
  prefixCommandProduct =
    commands: subcommands:
    builtins.concatMap (
      command:
      map (subcommand: {
        type = "prefix";
        cmd = "${command} ${subcommand}";
      }) subcommands
    ) commands;

  gitReadOnlyCommands =
    prefixCommandProduct
      [ "git" ]
      [
        "diff"
        "log"
        "show"
        "stash list"
        "stash show"
        "status"
      ];

  bazelExecutables = [
    "bazel"
    "bazelisk"
  ];

  bazelSubcommands = [
    "query"
    "cquery"
    "aquery"
    "info"
    "build"
    "test"
  ];

  bazelCommands = prefixCommandProduct bazelExecutables bazelSubcommands;

  nixDevelopBazelCommands =
    let
      commandFlags = [
        "--command"
        "-c"
      ];
      nixDevelopBazel = builtins.concatMap (
        flag: map (exe: "nix develop ${flag} ${exe}") bazelExecutables
      ) commandFlags;
    in
    prefixCommandProduct nixDevelopBazel bazelSubcommands;

  nixCommands =
    prefixCommandProduct
      [ "nix" ]
      [
        "eval"
        "build"
        "hash"
      ];

  cargoMetadataCommands =
    prefixCommandProduct
      [ "cargo" ]
      [
        "info"
        "search"
        "tree"
      ];
in
{
  # All allowed commands (no sudo - these are user-accessible commands)
  noSudo =
    gitReadOnlyCommands
    ++ bazelCommands
    ++ nixDevelopBazelCommands
    ++ nixCommands
    ++ [
      # TODO: Add more git read-only commands:
      # { type = "prefix"; cmd = "git branch"; }
      # { type = "prefix"; cmd = "git remote"; }
      # { type = "prefix"; cmd = "git tag"; }
      # { type = "prefix"; cmd = "git blame"; }
      # { type = "prefix"; cmd = "git reflog"; }

      # Home manager operations
      {
        type = "prefix";
        cmd = "home-manager build";
      }

      # Nix prefetch (read-only — fetches and prints hash without adding to store)
      {
        type = "prefix";
        cmd = "nix-prefetch-url";
      }
      {
        type = "exact";
        cmd = "pwd";
      }
      {
        type = "exact";
        cmd = "talosctl version";
      }
      {
        type = "prefix";
        cmd = "prettier";
      }
      {
        type = "prefix";
        cmd = "pre-commit run";
      }
    ]
    ++ cargoMetadataCommands;

  # TODO: Add build system queries:
  # { type = "prefix"; cmd = "bazelisk fetch"; }
  # { type = "prefix"; cmd = "npm list"; }
  # { type = "prefix"; cmd = "npm outdated"; }
  # { type = "prefix"; cmd = "npm audit"; }
  # { type = "prefix"; cmd = "pip list"; }
  # { type = "prefix"; cmd = "pip show"; }

  # TODO: Add test execution commands (safe - only writes to build artifacts):
  # { type = "exact"; cmd = "npm test"; }
  # { type = "exact"; cmd = "npm run test"; }
  # { type = "exact"; cmd = "cargo test"; }
  # { type = "exact"; cmd = "cargo check"; }
  # { type = "exact"; cmd = "cargo clippy"; }
}
