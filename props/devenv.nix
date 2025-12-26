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
    # Password stored in .devenv/state/pg_password (generated on first shell entry)
    database = "eval_results";
  };
  passwordFile = ".devenv/state/pg_password";
in {
  # Python/uv managed by root devenv.nix - this file only handles props-specific infra

  # PostgreSQL Docker container (managed via processes)
  # Network: props_default (created in enterShell, shared with agent containers)
  # Container name: props-postgres (accessible from other containers on props_default network)
  # Host access: localhost:5433
  processes.postgres.exec = ''
    # Stop and remove existing container if present
    docker rm -f ${pgConfig.containerName} 2>/dev/null || true

    # Read password from state file
    PG_PASSWORD=$(cat ${passwordFile})

    # Run PostgreSQL container
    # max_connections=200: Support higher parallel GEPA evaluation workloads
    docker run --rm \
      --name ${pgConfig.containerName} \
      --network props_default \
      -p ${pgConfig.port}:${pgConfig.containerPort} \
      -e POSTGRES_USER=${pgConfig.adminUser} \
      -e POSTGRES_PASSWORD="$PG_PASSWORD" \
      -e POSTGRES_DB=${pgConfig.database} \
      -v props_eval_results_data:/var/lib/postgresql/data \
      postgres:16 \
      -c max_connections=200
  '';

  # Environment variables (database connection parameters - single source of truth)
  env = {
    # Standard PostgreSQL client variables (host-side access)
    # PGPASSWORD is set dynamically in enterShell from .devenv/state/pg_password
    PGHOST = pgConfig.host;
    PGPORT = pgConfig.port;
    PGUSER = pgConfig.adminUser;
    PGDATABASE = pgConfig.database;

    # Project-specific: container routing (for Docker network communication)
    PROPS_DB_CONTAINER_NAME = pgConfig.containerName;
    PROPS_DB_CONTAINER_PORT = pgConfig.containerPort;
  };

  # On shell entry
  enterShell = ''
    set -euo pipefail

    # Generate PostgreSQL password if not exists
    mkdir -p .devenv/state
    if [[ ! -f ${passwordFile} ]]; then
      echo "Generating PostgreSQL password..."
      ${pkgs.openssl}/bin/openssl rand -base64 24 > ${passwordFile}
      chmod 600 ${passwordFile}
    fi
    export PGPASSWORD=$(cat ${passwordFile})

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

    echo "Props setup ready. Start PostgreSQL with: devenv up"
  '';
}
