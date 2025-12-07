#!/usr/bin/env bash
# Install dependencies and run pytest for a project
# Usage: run-pytest.sh <project_dir>
set -euo pipefail

project_dir="$1"
cd "$project_dir"

# UV version synced with flake.nix / .envrc
pip install uv==0.5.11

# Check if project needs system dependencies for Python bindings
if grep -qE "(dbus-python|PyGObject)" pyproject.toml 2>/dev/null; then
  sudo apt-get update
  # libdbus-1-dev: required for dbus-python
  # libgirepository1.0-dev: required for PyGObject
  # libcairo2-dev: required for pycairo (PyGObject dependency)
  sudo apt-get install -y libdbus-1-dev libgirepository1.0-dev libcairo2-dev
fi

# Install project dependencies
uv pip install --system -e ".[dev]" || uv pip install --system -e .

# Install Playwright browsers if playwright is installed
if uv pip show playwright >/dev/null 2>&1; then
  playwright install --with-deps chromium
fi

# Run tests if pytest is available
if uv pip show pytest >/dev/null 2>&1; then
  pytest -v
else
  echo "pytest not installed in this project, skipping tests"
fi
