"""Configuration constants for Harbor OIDC investigation."""

import os

# Timeouts
TIMEOUT_SHORT = 15  # For quick commands
TIMEOUT_MEDIUM = 60  # For medium commands
TIMEOUT_LONG = 300  # For long-running commands like log collection
MAX_WORKERS = 20  # Parallel execution limit

# Namespaces - Production environment
HARBOR_NAMESPACE = os.getenv("HARBOR_NAMESPACE", "harbor")
AUTHENTIK_NAMESPACE = os.getenv("AUTHENTIK_NAMESPACE", "authentik")
VAULT_NAMESPACE = os.getenv("VAULT_NAMESPACE", "vault")

# Harbor Components
HARBOR_CORE = "harbor-core"
HARBOR_PORTAL = "harbor-portal"
HARBOR_JOBSERVICE = "harbor-jobservice"
HARBOR_REGISTRY = "harbor-registry"
HARBOR_TRIVY = "harbor-trivy"
HARBOR_REDIS = "harbor-redis"
HARBOR_DATABASE = "harbor-database"
HARBOR_OIDC_CONFIG_JOB = "oidc-config"
HARBOR_ADMIN_INIT_JOB = "admin-init"

# Authentik Components
AUTHENTIK_SERVER = "authentik-server"
AUTHENTIK_WORKER = "authentik-worker"
AUTHENTIK_POSTGRESQL = "authentik-postgresql"
AUTHENTIK_REDIS = "authentik-redis"

# Secrets
HARBOR_OIDC_SECRET = "harbor-oidc-secret"
HARBOR_ADMIN_PASSWORD_KEY = "HARBOR_ADMIN_PASSWORD"

# Database
HARBOR_DATABASE_POD = "harbor-database-0"  # This is a StatefulSet, so name is stable
# Note: HARBOR_CORE_POD should be dynamically selected as it's a Deployment
POSTGRES_USER = "postgres"
REGISTRY_DB = "registry"

# API Endpoints - Production URLs
HARBOR_HOST = "registry.k3s.agentydragon.com"
AUTHENTIK_BASE_URL = "https://auth.k3s.agentydragon.com"
HARBOR_BASE_URL = f"https://{HARBOR_HOST}"

# Common test commands
OIDC_LOGIN_CURL_CMD = [
    "curl",
    "-s",
    "-c",
    "/tmp/harbor_session.txt",
    "http://localhost:8080/c/oidc/login?redirect_url=/harbor/projects",
]
