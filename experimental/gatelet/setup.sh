#!/usr/bin/env bash
# Expects to run from repo root.

set -e

warn() { echo "⚠️  $* (ignored)"; }
run() { "$@" || warn "$*"; }

export DEBIAN_FRONTEND=noninteractive


##############################################################################
# 0.  Proxy & CA preset
#     Codex already sets HTTP_PROXY / HTTPS_PROXY and PIP_CERT / NODE_EXTRA_CA_CERTS
#     We only need to teach APT to use the proxy; everything else (pip, curl…)
#     respects the env-vars automatically.
##############################################################################
[[ -n "${HTTP_PROXY:-}"  ]] && echo "Acquire::http::Proxy  \"${HTTP_PROXY}\";"  > /etc/apt/apt.conf.d/01proxy
[[ -n "${HTTPS_PROXY:-}" ]] && echo "Acquire::https::Proxy \"${HTTPS_PROXY}\";" >> /etc/apt/apt.conf.d/01proxy

# ── System packages ──────────────────────────────────────────────────────────
# Those won't work -- getting:
#   'Cannot initiate the connection to archive.ubuntu.com:80 (185.125.190.81). - connect (101: Network is unreachable)'
apt-get update -qq
apt-get install -y --no-install-recommends \
  build-essential python3-venv python3-dev curl \
  postgresql postgresql-contrib libpq-dev \
  ca-certificates
# NodeJS + NPM already installed

# Expose Postgres binaries system-wide
##############################################################################
PG_BIN="$(pg_config --bindir)"            # e.g. /usr/lib/postgresql/16/bin
export PATH="$PG_BIN:$PATH"               # for the remainder of setup.sh

# persist for all future shells
echo "export PATH=$PG_BIN:\$PATH" | tee /etc/profile.d/pg-bin.sh /root/.bashrc ~postgres/.bashrc
chmod +x /etc/profile.d/pg-bin.sh

# Initialise and launch a local Postgres that survives the sandbox
##############################################################################
echo "export IS_CODEX_ENV=1" >> /root/.bashrc

# Dev hygiene
##############################################################################
pip install pre-commit
pre-commit install

# Set up virtualenv
##############################################################################

python_env_setup() {
    pip install --upgrade pip wheel
    pip install -e experimental/gatelet[dev]

    # Install browsers (headless mode)
    # python -m playwright install --with-deps chromium-headless-shell # firefox webkit chromium
}

# pip install --upgrade pip setuptools wheel
# VENV=experimental/gatelet/.venv
# python -m venv $VENV
# source $VENV/bin/activate

python_env_setup

# deactivate
# echo "source $(realpath $VENV)/bin/activate" >> /root/.bashrc

echo "Bootstrap finished"
exit 0
