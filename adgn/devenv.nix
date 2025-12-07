{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: let
  # PostgreSQL configuration (single source of truth)
  pgConfig = {
    host = "127.0.0.1";
    port = "5433";
    containerName = "props-postgres";
    adminUser = "postgres";
    adminPassword = "props_admin_pass";
    agentUser = "agent_user";
    agentPassword = "agent_password_changeme";
    database = "eval_results";
  };
in {
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

  # Background processes (start with: `devenv up`)
  processes.vite.exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";

  # PostgreSQL Docker container (managed via processes)
  # Network: props_default (created in enterShell, shared with prompt-optimizer agent containers)
  # Container name: props-postgres (accessible from other containers on props_default network)
  # Host access: localhost:5433
  processes.postgres.exec = ''
    # Stop and remove existing container if present
    docker rm -f ${pgConfig.containerName} 2>/dev/null || true

    # Run PostgreSQL container
    # max_connections=200: Support higher parallel GEPA evaluation workloads
    docker run --rm \
      --name ${pgConfig.containerName} \
      --network props_default \
      -p ${pgConfig.port}:5432 \
      -e POSTGRES_USER=${pgConfig.adminUser} \
      -e POSTGRES_PASSWORD=${pgConfig.adminPassword} \
      -v props_eval_results_data:/var/lib/postgresql/data \
      postgres:16 \
      -c max_connections=200
  '';

  # Environment variables (database connection parameters - single source of truth)
  env = {
    # Structured database configuration (preferred)
    PROPS_DB_HOST = pgConfig.host;
    PROPS_DB_PORT = pgConfig.port;
    PROPS_DB_CONTAINER_NAME = pgConfig.containerName;
    PROPS_DB_ADMIN_USER = pgConfig.adminUser;
    PROPS_DB_ADMIN_PASSWORD = pgConfig.adminPassword;
    PROPS_DB_AGENT_USER = pgConfig.agentUser;
    PROPS_DB_AGENT_PASSWORD = pgConfig.agentPassword;
    PROPS_DB_NAME = pgConfig.database;
  };

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

    # Ensure Docker networks exist for Postgres + agent containers
    if command -v docker &> /dev/null; then
      if ! docker network inspect props_default &> /dev/null; then
        echo "Creating Docker network 'props_default' for container communication..."
        docker network create props_default
      fi
      # Also create props-network for HTTP mode MCP (allows host access, blocks internet)
      if ! docker network inspect props-network &> /dev/null; then
        echo "Creating Docker network 'props-network' for MCP HTTP mode..."
        docker network create props-network --internal=true
      fi
    fi

    python --version
    echo "Tip: run 'devenv up' to start Vite UI dev server + PostgreSQL container in the background, or use 'ui-dev'/'mini-codex-serve' scripts."
    echo "Props setup ready. Start PostgreSQL with: devenv up"
  '';
}
