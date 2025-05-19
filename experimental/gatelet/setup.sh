#!/usr/bin/env bash
# Expects to run from repo root.

set -uo pipefail

warn() { echo "⚠️  $* (ignored)"; }
run() { "$@" || warn "$*"; }

export DEBIAN_FRONTEND=noninteractive


##############################################################################
# 0.  Proxy & CA preset
#     Codex already sets HTTP_PROXY / HTTPS_PROXY and PIP_CERT / NODE_EXTRA_CA_CERTS
#     We only need to teach APT to use the proxy; everything else (pip, curl…)
#     respects the env-vars automatically.
##############################################################################
if [[ -n "${HTTP_PROXY:-}" ]];  then
  echo "Acquire::http::Proxy  \"${HTTP_PROXY}\";"  > /etc/apt/apt.conf.d/01proxy
fi
if [[ -n "${HTTPS_PROXY:-}" ]]; then
  echo "Acquire::https::Proxy \"${HTTPS_PROXY}\";" >> /etc/apt/apt.conf.d/01proxy
fi

# ── System packages ──────────────────────────────────────────────────────────
# Those won't work -- getting:
#   'Cannot initiate the connection to archive.ubuntu.com:80 (185.125.190.81). - connect (101: Network is unreachable)'
apt-get update
apt-get install -y \
  build-essential python3-venv python3-dev curl \
  postgresql postgresql-contrib libpq-dev \
  ca-certificates
# NodeJS + NPM already installed

# ##############################################################################
# 2.  Initialise and launch a local Postgres that survives the sandbox
##############################################################################
PGDATA=/workspace/pgdata
su - postgres -c "initdb -D $PGDATA"
su - postgres -c "pg_ctl -D $PGDATA -o '-c listen_addresses=localhost' -w start"
su - postgres -c "createdb gatelet"

# ── Python virtualenv ────────────────────────────────────────────────────────
pip install --upgrade pip setuptools wheel

# Dev hygiene
pip install pre-commit
pre-commit install

# venv for gatelet
VENV=experimental/gatelet/.venv
python -m venv $VENV
source /venv/bin/activate
pip install --upgrade pip wheel
pip install -e experimental/gatelet[dev]
deactivate

##############################################################################
# 4.  Persist app-visible env vars (agent runs in a NEW shell)
##############################################################################
{
  echo "export VIRTUAL_ENV=$VENV"
  echo 'export PATH=$VIRTUAL_ENV/bin:$PATH'
  echo 'export DATABASE_URL=postgresql+psycopg://postgres@localhost/gatelet'
} >> /root/.bashrc

echo "✅ Bootstrap finished (errors above were ignored)."
