#!/usr/bin/env bash
# Expects to run from repo root.
# Expects that setup.sh in repo root has already been run.

set -e

warn() { echo "⚠️  $* (ignored)"; }
run() { "$@" || warn "$*"; }

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y --no-install-recommends \
  postgresql postgresql-contrib libpq-dev \
  wget curl gnupg

# Expose Postgres binaries system-wide
##############################################################################
PG_BIN="$(pg_config --bindir)"            # e.g. /usr/lib/postgresql/16/bin

# set PATH for future shells
echo "export PATH=$PG_BIN:\$PATH" | tee /etc/profile.d/pg-bin.sh /root/.bashrc ~postgres/.bashrc
chmod +x /etc/profile.d/pg-bin.sh

echo "export IS_CODEX_ENV=1" >> /root/.bashrc

# Set up virtualenv
##############################################################################
python_env_setup() {
    pip install --upgrade pip wheel

    # When this script is executed we are still in the repository root even
    # though the file itself lives in the *gatelet/* sub-folder.  Tell pip
    # explicitly that we want to install the local *directory* rather than a
    # package from PyPI by prefixing the path with "./".

    echo "++ pip install -e ./gatelet[dev]"
    pip install -e "./gatelet[dev]"
}

pip install --upgrade pip setuptools wheel
VENV=gatelet/.venv
python -m venv $VENV
source $VENV/bin/activate

python_env_setup

apt update && apt install -y  libgtk-4-1  libgraphene-1.0-0  libwoff1  libvpx9  libevent-2.1-7t64  libopus0  libgstreamer-plugins-base1.0-0  libgstreamer-plugins-bad1.0-0  libgstreamer-gl1.0-0  libflite1  libwebpdemux2  libavif16  libharfbuzz-icu0  libwebpmux3  libenchant-2-2  libsecret-1-0  libhyphen0  libmanette-0.2-0  libgles2  libx264-164
playwright install

deactivate
echo "source $(realpath $VENV)/bin/activate" >> /root/.bashrc
