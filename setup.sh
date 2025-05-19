#!/usr/bin/env bash
# Bootstrap full dev environment (Python + PostgreSQL + Node/Vite/React + LLM tooling)
# Continues even if individual steps fail.

set -uo pipefail

warn() { echo "⚠️  $* (ignored)"; }
run() { "$@" || warn "$*"; }

# ── System packages ──────────────────────────────────────────────────────────
run sudo apt-get update
run sudo apt-get install -y \
     build-essential python3-venv python3-dev curl git \
     postgresql postgresql-contrib libpq-dev \
     nodejs npm

# ── PostgreSQL basic setup ───────────────────────────────────────────────────
# run sudo systemctl enable --now postgresql
# run sudo -u postgres createuser --superuser "${USER}"
# run sudo -u postgres createdb "${USER}"

# ── Node toolchain (Vite + React) ────────────────────────────────────────────
run sudo npm install -g corepack
run corepack enable
run corepack prepare pnpm@latest --activate
run pnpm add -g vite
run pnpm install react react-dom

# ── Python virtualenv ────────────────────────────────────────────────────────
PYTHON=${PYTHON:-python3}
VENV_DIR=${VENV_DIR:-.venv}

run $PYTHON -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

run pip install --upgrade pip setuptools wheel
[ -f requirements_lock.txt ] && run pip install -r requirements_lock.txt

# Editable sub-projects
run pip install -e experimental/gatelet[dev]
run pip install -e llm/mcp/habitify

# PostgreSQL drivers (sync & async)
run pip install "psycopg[binary,pool]" asyncpg sqlalchemy
run pip install aiosqlite

# LLM / NLP helpers
# run pip install sentence-transformers openai tiktoken

# Home-Assistant clients & misc
run pip install homeassistant homeassistant-cli aiohttp pyyaml

# Dev hygiene
run pip install pre-commit
run pre-commit install

echo
echo "✅ Bootstrap finished (errors above were ignored)."
echo "   Activate with: source \"$VENV_DIR/bin/activate\""
# echo "   Postgres URL:  postgresql://$USER@localhost/$USER"

