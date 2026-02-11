{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Basic packages available in the shell
  # stdenv.cc.cc.lib provides libstdc++.so.6 needed by numpy, jsonnet, etc.
  packages = [pkgs.git pkgs.nodejs_20 pkgs.stdenv.cc.cc.lib pkgs.zlib];

  # Python (devenv-managed venv)
  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = ["dev" "gepa" "matrix"];
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

  # PostgreSQL container (replaces docker-compose.yml)
  containers.postgres = {
    name = "props-postgres";
    image = "postgres:16";
    ports = ["5433:5432"];
    environment = {
      POSTGRES_USER = "postgres";
      POSTGRES_PASSWORD = "props_admin_pass";
      # Note: Creates 'postgres' database by default
      # Additional databases (eval_results, eval_results_test) created via init_db.sh
    };
    volumes = [
      "props_eval_results_data:/var/lib/postgresql/data"
    ];
    networks = ["props_default"];
    cmd = []; # Use default postgres startup command
  };

  # Background processes (start with: `devenv up`)
  processes.vite.exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";

  # On shell entry, ensure the project is installed (editable) with dev extras
  # Install into the active devenv-managed venv so `pytest`, `ruff`, etc. are on PATH
  # Lightweight shell entry; dependency management handled by uv sync
  enterShell = ''
    set -euo pipefail

    # Add native library paths for Python C extensions (numpy, jsonnet, etc.)
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

    # Use Nix-provided Playwright browsers (fixes GLIBC compatibility)
    export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
    export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true

    python --version
    echo "Tip: run 'devenv up' to start Vite UI dev server + PostgreSQL container in the background, or use 'ui-dev'/'mini-codex-serve' scripts."
  '';
}
