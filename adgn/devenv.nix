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
    port = "5433"; # Host-mapped port
    containerName = "props-postgres";
    containerPort = "5432"; # Internal container port (for Docker network communication)
    adminUser = "postgres";
    adminPassword = "props_admin_pass";
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
  scripts."ui-dev".description = "Run Vite dev server for Agent UI (http://127.0.0.1:5173)";

  scripts."ui-build".exec = "npm --prefix ./src/adgn/agent/web run build";
  scripts."ui-build".description = "Build Agent UI assets into server/static/web";

  scripts."agent-serve".exec = "python -m adgn.agent.cli serve --host 127.0.0.1 --port 8765";
  scripts."agent-serve".description = "Start Agent backend + FastAPI UI server (http://127.0.0.1:8765)";

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
      -p ${pgConfig.port}:${pgConfig.containerPort} \
      -e POSTGRES_USER=${pgConfig.adminUser} \
      -e POSTGRES_PASSWORD=${pgConfig.adminPassword} \
      -v props_eval_results_data:/var/lib/postgresql/data \
      postgres:16 \
      -c max_connections=200
  '';

  # Environment variables (database connection parameters - single source of truth)
  env = {
    # Standard PostgreSQL client variables (admin credentials, host-side access)
    PGHOST = pgConfig.host;
    PGPORT = pgConfig.port;
    PGUSER = pgConfig.adminUser;
    PGPASSWORD = pgConfig.adminPassword;
    PGDATABASE = pgConfig.database;

    # Project-specific: container routing (for Docker network communication)
    PROPS_DB_CONTAINER_NAME = pgConfig.containerName;
    PROPS_DB_CONTAINER_PORT = pgConfig.containerPort;
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

    # Ensure Docker network exists for Postgres + agent containers
    # Non-internal network allows:
    # - Container-to-container communication (postgres access)
    # - Container-to-host communication (MCP HTTP mode)
    if command -v docker &> /dev/null; then
      if ! docker network inspect props_default &> /dev/null; then
        echo "Creating Docker network 'props_default' for postgres + agent containers..."
        docker network create props_default
      fi
    fi

    python --version
    echo "Tip: run 'devenv up' to start Vite UI dev server + PostgreSQL container in the background, or use 'ui-dev'/'agent-serve' scripts."
    echo "Props setup ready. Start PostgreSQL with: devenv up"
  '';
}
