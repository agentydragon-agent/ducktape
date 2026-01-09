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

  # OCI Registry configuration (for agent packages as images)
  registryConfig = {
    host = "127.0.0.1";
    port = "5050"; # Host-mapped port
    containerName = "props-registry";
    containerPort = "5000"; # Internal container port
  };
in {
  # Python/uv managed by root devenv.nix - this file only handles props-specific infra

  # Node.js for frontend development
  languages.javascript = {
    enable = true;
    package = pkgs.nodejs_22;
    pnpm.enable = true;
  };

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

  # OCI Registry Docker container (for agent packages as images)
  # Network: props_default (shared with postgres and agent containers)
  # Container name: props-registry (accessible from other containers on props_default network)
  # Host access: localhost:5050
  processes.registry.exec = ''
    # Stop and remove existing container if present
    docker rm -f ${registryConfig.containerName} 2>/dev/null || true

    # Run registry container
    docker run --rm \
      --name ${registryConfig.containerName} \
      --network props_default \
      -p ${registryConfig.port}:${registryConfig.containerPort} \
      -v props_registry_data:/var/lib/registry \
      registry:2
  '';

  # Registry proxy for ACL enforcement and metadata tracking
  # Agents connect to the proxy (port 5051), which forwards to registry (port 5050)
  # Proxy enforces namespace isolation and records image refs in database
  processes.registry_proxy.exec = ''
    echo "Waiting for postgres..."
    until pg_isready -q; do sleep 1; done
    echo "Waiting for registry..."
    until curl -s http://localhost:${registryConfig.port}/v2/ > /dev/null; do sleep 1; done

    export PROPS_REGISTRY_UPSTREAM_URL="http://localhost:${registryConfig.port}"
    uvicorn props.core.registry.proxy:app --host 0.0.0.0 --port 5051 --log-level warning
  '';

  # Periodic database backup (every 6 hours, keeps 7 days)
  # Uses PG* env vars from devenv.env; PGPASSWORD read from state file
  processes.pg_backup.exec = ''
    BACKUP_DIR=".devenv/state/pg_backups"
    mkdir -p "$BACKUP_DIR"
    export PGPASSWORD=$(cat ${passwordFile})

    do_backup() {
      local TIMESTAMP=$(date +%Y%m%d_%H%M%S)
      local BACKUP_FILE="$BACKUP_DIR/props_backup_$TIMESTAMP.sql.gz"
      echo "Creating backup: $BACKUP_FILE"
      pg_dump | gzip > "$BACKUP_FILE"
    }

    echo "Waiting for postgres..."
    until pg_isready -q; do sleep 2; done

    do_backup
    while true; do
      sleep 21600  # 6 hours
      do_backup
      find "$BACKUP_DIR" -name "props_backup_*.sql.gz" -mtime +7 -delete
    done
  '';

  # Enable process logs in TUI.
  # devenv wraps process-compose commands through devenv-tasks to enable task
  # dependencies between processes. However, devenv-tasks captures stdout/stderr
  # into its own activity system and hides logs by default (showOutput=false).
  # This makes the process-compose TUI log panel empty. Override to show logs.
  # See: https://github.com/cachix/devenv/issues/2037
  tasks."devenv:processes:postgres".showOutput = true;

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

    # OCI Registry configuration
    # Host-side access (for bazel push, local development)
    PROPS_REGISTRY_HOST = registryConfig.host;
    PROPS_REGISTRY_PORT = registryConfig.port;
    PROPS_REGISTRY_PROXY_PORT = "5051"; # Proxy port for agent access with ACL
    # Container-side access (for agents pulling images from within Docker network)
    PROPS_REGISTRY_CONTAINER_NAME = registryConfig.containerName;
    PROPS_REGISTRY_CONTAINER_PORT = registryConfig.containerPort;
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

    echo ""
    echo "Props dev environment ready"
    echo "  devenv up                          → starts postgres, registry, periodic backup"
    echo "  bazelisk run //props/frontend:dev  → frontend + backend (from direnv shell)"
    echo ""
    echo "Database backup commands:"
    echo "  props db backup        → create manual backup"
    echo "  props db restore FILE  → restore from backup"
    echo "  props db list-backups  → list available backups"
    echo ""
    echo "Registry: http://localhost:${registryConfig.port} (direct), http://localhost:5051 (proxy with ACL)"
    echo ""
  '';
}
