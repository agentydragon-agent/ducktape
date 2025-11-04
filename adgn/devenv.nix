{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Basic packages available in the shell
  packages = [pkgs.git pkgs.nodejs_20];

  # Python (devenv-managed venv)
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

  # Convenience scripts (available inside the dev shell)
  scripts."ui-dev".exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";
  scripts."ui-dev".description = "Run Vite dev server for MiniCodex UI (http://127.0.0.1:5173)";

  scripts."ui-build".exec = "npm --prefix ./src/adgn/agent/web run build";
  scripts."ui-build".description = "Build MiniCodex UI assets into server/static/web";

  scripts."mini-codex-serve".exec = "python -m adgn.agent.cli serve --host 127.0.0.1 --port 8765";
  scripts."mini-codex-serve".description = "Start MiniCodex backend + FastAPI UI server (http://127.0.0.1:8765)";

  # Background processes (start with: `devenv up`)
  processes.vite.exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";

  # On shell entry, ensure the project is installed (editable) with dev extras
  # Install into the active devenv-managed venv so `pytest`, `ruff`, etc. are on PATH
  # Lightweight shell entry; dependency management handled by uv sync
  enterShell = ''
    set -euo pipefail
    python --version
    echo "Tip: run 'devenv up' to start the Vite UI dev server in the background, or use 'ui-dev'/'mini-codex-serve' scripts."
  '';
}
