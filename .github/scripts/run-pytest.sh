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
  # libgirepository-2.0-dev: required for PyGObject (girepository-2.0 API)
  # libcairo2-dev: required for pycairo (PyGObject dependency)
  sudo apt-get install -y libdbus-1-dev libgirepository-2.0-dev libcairo2-dev
fi

# Determine Python version from pyproject.toml (default to 3.11)
# Parse requires-python: ">=3.12" -> "3.12", ">=3.11" -> "3.11"
required_python="3.11"
if grep -qE 'requires-python.*>=\s*3\.12' pyproject.toml 2>/dev/null; then
  required_python="3.12"
fi

# Create virtual environment with appropriate Python version
python_bin="python${required_python}"
if ! command -v "$python_bin" &>/dev/null; then
  echo "Warning: $python_bin not found, falling back to python3"
  python_bin="python3"
fi

uv venv --python="$python_bin" .venv
# shellcheck disable=SC1091
source .venv/bin/activate

# Install project dependencies
uv pip install -e ".[dev]" || uv pip install -e .

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
