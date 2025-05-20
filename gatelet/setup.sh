#!/usr/bin/env bash
# Expects to run from repo root.
# Expects that setup.sh in repo root has already been run.

set -e

warn() { echo "⚠️  $* (ignored)"; }
run() { "$@" || warn "$*"; }

export DEBIAN_FRONTEND=noninteractive

apt-get install -y --no-install-recommends \
  postgresql postgresql-contrib libpq-dev

# Expose Postgres binaries system-wide
##############################################################################
PG_BIN="$(pg_config --bindir)"            # e.g. /usr/lib/postgresql/16/bin

# set PATH for future shells
echo "export PATH=$PG_BIN:\$PATH" | tee /etc/profile.d/pg-bin.sh /root/.bashrc ~postgres/.bashrc
chmod +x /etc/profile.d/pg-bin.sh

# Initialise and launch a local Postgres that survives the sandbox
##############################################################################
echo "export IS_CODEX_ENV=1" >> /root/.bashrc

# Set up virtualenv
##############################################################################

python_env_setup() {
    pip install --upgrade pip wheel
    #pip install -e gatelet[dev]
    pip install \
    "pytest==7.3.1" \
    "pytest-asyncio==0.21.0" \
    "pytest-timeout==2.2.0" \
    "isort==5.12.0" \
    "pyhamcrest==2.0.4" \
    "httpx==0.24.1" \
    "pytest-postgresql==4.1.1" \
    "sqlalchemy-stubs==0.4.0" \
    "fastapi>=0.104.0" \
    "uvicorn[standard]>=0.23.2" \
    "SQLAlchemy>=2.0.0" \
    "alembic>=1.12.0" \
    "psycopg2-binary>=2.9.6" \
    "asyncpg>=0.27.0 "\
    "cryptography>=41.0.0" \
    "jinja2>=3.1.2" \
    "python-multipart>=0.0.9" \
    "pydantic>=2.4.0" \
    "compact_json>=1.0.0" \
    "homeassistant-api" \
    "passlib" \
    "tomlkit" \
    "fastapi-csrf-protect" \
    "fastapi-users[sqlalchemy,argon2]" \
    "fastapi-sessions"
}

# pip install --upgrade pip setuptools wheel
# VENV=gatelet/.venv
# python -m venv $VENV
# source $VENV/bin/activate

python_env_setup

# deactivate
# echo "source $(realpath $VENV)/bin/activate" >> /root/.bashrc
