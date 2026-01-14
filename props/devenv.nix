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
    registryPort = "5050"; # Registry direct access (host-mapped)
    proxyPort = "5051"; # Proxy with ACL (host-mapped)
    registryContainerName = "props-registry";
    registryContainerPort = "5000"; # Internal registry port
    proxyContainerName = "props-registry-proxy";
    proxyContainerPort = "5051"; # Internal proxy port
  };
in {
  # Python/uv managed by root devenv.nix - this file only handles props-specific infra

  # bazelisk for building/pushing agent images
  packages = [pkgs.bazelisk];

  # Node.js for frontend development
  languages.javascript = {
    enable = true;
    package = pkgs.nodejs_22;
    pnpm.enable = true;
  };

  # PostgreSQL Docker container (managed via processes)
  # Networks: default bridge (host port) + props-internal + props-agents
  # Host access: localhost:5433
  processes.postgres.exec = ''
    # Stop and remove existing container if present
    docker rm -f ${pgConfig.containerName} 2>/dev/null || true

    # Read password from state file
    PG_PASSWORD=$(cat ${passwordFile})

    # Run PostgreSQL container on default bridge (for host port binding)
    # max_connections=200: Support higher parallel GEPA evaluation workloads
    # Note: --internal networks block host port publishing, so start on default bridge first
    docker run -d --rm \
      --name ${pgConfig.containerName} \
      -p ${pgConfig.port}:${pgConfig.containerPort} \
      -e POSTGRES_USER=${pgConfig.adminUser} \
      -e POSTGRES_PASSWORD="$PG_PASSWORD" \
      -e POSTGRES_DB=${pgConfig.database} \
      -v props_eval_results_data:/var/lib/postgresql/data \
      postgres:16 \
      -c max_connections=200

    # Connect to internal networks for registry proxy and agent access
    docker network connect props-internal ${pgConfig.containerName}
    docker network connect props-agents ${pgConfig.containerName}

    # Follow logs to keep process-compose happy
    docker logs -f ${pgConfig.containerName}
  '';

  # OCI Registry Docker container (for agent packages as images)
  # Networks: default bridge (host port access) + props-internal (proxy access)
  # Container name: props-registry
  # Host access: localhost:5050 (for Bazel push)
  processes.registry.exec = ''
    # Stop and remove existing container if present
    docker rm -f ${registryConfig.registryContainerName} 2>/dev/null || true

    # Start registry on default bridge (for host port binding), then connect to internal network
    # Note: --internal networks block host port publishing, so we start on default bridge first
    docker run -d --rm \
      --name ${registryConfig.registryContainerName} \
      -p ${registryConfig.registryPort}:${registryConfig.registryContainerPort} \
      -v props_registry_data:/var/lib/registry \
      registry:2

    # Connect to internal network for proxy communication
    docker network connect props-internal ${registryConfig.registryContainerName}

    # Follow logs to keep process-compose happy
    docker logs -f ${registryConfig.registryContainerName}
  '';

  # Registry proxy for ACL enforcement and metadata tracking
  # Networks: default bridge (host port) + props-internal (registry/postgres) + props-agents (agents)
  # Host access: localhost:5051 (for debugging)
  # Agents connect to the proxy, which forwards to registry with ACL checks
  processes.registry_proxy.exec = ''
    echo "Waiting for postgres..."
    until pg_isready -q; do sleep 1; done
    echo "Waiting for registry..."
    until curl -s http://localhost:${registryConfig.registryPort}/v2/ > /dev/null; do sleep 1; done

    # Stop and remove existing container if present
    docker rm -f ${registryConfig.proxyContainerName} 2>/dev/null || true

    # Read password from state file for database connection
    PG_PASSWORD=$(cat ${passwordFile})

    # Check if proxy image exists, build it if not
    if ! docker image inspect props-registry-proxy:latest >/dev/null 2>&1; then
      echo "Proxy image not found, building..."
      # devenv runs from props/, go up to repo root for Bazel
      (cd .. && bazelisk run //props/registry_proxy:load) || {
        echo "ERROR: Failed to build proxy image"
        echo "  Try manually: bazelisk run //props/registry_proxy:load"
        exit 1
      }
    fi

    # Run proxy on default bridge (for host port binding), then connect to internal networks
    # Note: --internal networks block host port publishing
    docker run -d --rm --name ${registryConfig.proxyContainerName} \
      -p ${registryConfig.proxyPort}:${registryConfig.proxyContainerPort} \
      -e PROPS_REGISTRY_UPSTREAM_URL=http://${registryConfig.registryContainerName}:${registryConfig.registryContainerPort} \
      -e PGHOST=${pgConfig.containerName} -e PGPORT=${pgConfig.containerPort} \
      -e PGUSER=${pgConfig.adminUser} -e PGPASSWORD="$PG_PASSWORD" \
      -e PGDATABASE=${pgConfig.database} \
      props-registry-proxy:latest

    # Connect to internal networks for registry/postgres access and agent access
    docker network connect props-internal ${registryConfig.proxyContainerName}
    docker network connect props-agents ${registryConfig.proxyContainerName}

    # Wait for proxy to be healthy (check /v2/ endpoint)
    echo "Waiting for proxy to be ready..."
    for i in {1..30}; do
      if curl -sf http://localhost:${registryConfig.proxyPort}/v2/ >/dev/null 2>&1; then
        echo "Proxy is ready and responding"
        break
      fi
      if [ $i -eq 30 ]; then
        echo "ERROR: Proxy failed to start within 30 seconds"
        echo "Check logs: docker logs ${registryConfig.proxyContainerName}"
        exit 1
      fi
      sleep 1
    done

    # Follow logs to keep process-compose happy
    docker logs -f ${registryConfig.proxyContainerName}
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
    PROPS_REGISTRY_PORT = registryConfig.registryPort;
    PROPS_REGISTRY_PROXY_PORT = registryConfig.proxyPort;
    # Container-side access (for agents pulling images from within Docker network)
    PROPS_REGISTRY_CONTAINER_NAME = registryConfig.registryContainerName;
    PROPS_REGISTRY_CONTAINER_PORT = registryConfig.registryContainerPort;
    PROPS_REGISTRY_PROXY_CONTAINER_NAME = registryConfig.proxyContainerName;
    PROPS_REGISTRY_PROXY_CONTAINER_PORT = registryConfig.proxyContainerPort;
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

    # Ensure Docker networks exist for proper isolation
    # props-internal: registry, proxy, postgres (not accessible to agents)
    # props-agents: proxy, postgres, agent containers (agents can only reach proxy)
    if command -v docker &> /dev/null; then
      if ! docker network inspect props-internal &> /dev/null; then
        echo "Creating Docker network 'props-internal' for registry + proxy + postgres..."
        docker network create props-internal --internal
      fi
      if ! docker network inspect props-agents &> /dev/null; then
        echo "Creating Docker network 'props-agents' for proxy + postgres + agents..."
        docker network create props-agents
      fi
      # Remove legacy props_default network if it exists
      if docker network inspect props_default &> /dev/null 2>&1; then
        echo "Removing legacy 'props_default' network..."
        docker network rm props_default 2>/dev/null || echo "  (network in use, will remove on next startup)"
      fi
    fi

    echo ""
    echo "Props dev environment"
    echo "  devenv up    → postgres, registry, proxy"
    echo "  bazelisk run //props/frontend:dev  → frontend + backend"
    echo "  bazelisk run //props/core:props -- --help"
    echo "  Registry: localhost:${registryConfig.registryPort} (direct), localhost:${registryConfig.proxyPort} (proxy)"
  '';
}
