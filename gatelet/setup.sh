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
    pip install -e gatelet[dev]

    # Install browsers (headless mode)
    # python -m playwright install --with-deps chromium-headless-shell # firefox webkit chromium
}

# pip install --upgrade pip setuptools wheel
# VENV=gatelet/.venv
# python -m venv $VENV
# source $VENV/bin/activate

python_env_setup

# deactivate
# echo "source $(realpath $VENV)/bin/activate" >> /root/.bashrc
