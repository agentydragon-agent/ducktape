{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: let
  passwordFile = ".devenv/state/pg_password";
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

  # Environment variables (database connection parameters)
  env = {
    # Standard PostgreSQL client variables (host-side access)
    # PGPASSWORD is set dynamically in enterShell from .devenv/state/pg_password
    PGHOST = "127.0.0.1";
    PGPORT = "5433";
    PGUSER = "postgres";
    PGDATABASE = "eval_results";

    # Project-specific: container routing (for Docker network communication)
    PROPS_DB_CONTAINER_NAME = "props-postgres";
    PROPS_DB_CONTAINER_PORT = "5432";

    # OCI Registry configuration
    # Host-side access (for bazel push, local development)
    PROPS_REGISTRY_HOST = "127.0.0.1";
    PROPS_REGISTRY_PORT = "5050";
    PROPS_REGISTRY_PROXY_PORT = "5051";
    # Container-side access (for agents pulling images from within Docker network)
    PROPS_REGISTRY_CONTAINER_NAME = "props-registry";
    PROPS_REGISTRY_CONTAINER_PORT = "5000";
    PROPS_REGISTRY_PROXY_CONTAINER_NAME = "props-registry-proxy";
    PROPS_REGISTRY_PROXY_CONTAINER_PORT = "5051";
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

    echo ""
    echo "Props dev environment"
    echo "  docker compose up -d   → postgres, registry, proxy"
    echo "  bazelisk run //props/frontend:dev  → frontend + backend"
    echo "  bazelisk run //props/core:props -- --help"
  '';
}
