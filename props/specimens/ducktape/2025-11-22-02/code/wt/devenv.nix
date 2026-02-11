{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Native tools and headers needed for wt development
  packages = with pkgs; [
    git
    libgit2
    pkg-config
  ];

  # Python environment managed by devenv + uv
  languages.python = {
    enable = true;
    package = pkgs.python311;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = ["dev"];
      };
    };
  };

  # Convenience commands available inside the dev shell
  scripts."wt-tests".exec = "uv run pytest";
  scripts."wt-tests".description = "Run the full pytest suite";

  scripts."wt-lint".exec = "uv run ruff check .";
  scripts."wt-lint".description = "Run Ruff lint checks";

  scripts."wt-typecheck".exec = "uv run mypy src tests";
  scripts."wt-typecheck".description = "Run mypy against src/ and tests/";

  enterShell = ''
    set -euo pipefail
    if ! command -v gitstatusd >/dev/null 2>&1; then
      echo "Warning: gitstatusd not found on PATH; integration tests will fail." >&2
    fi
    python --version
    echo "wt devenv ready. Try 'wt-tests' (pytest), 'wt-lint', or 'wt-typecheck'."
  '';
}
