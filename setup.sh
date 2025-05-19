#!/usr/bin/env bash
# Expects to run from repo root.
set -e

# Dev hygiene
##############################################################################
pip install pre-commit
pre-commit install --install-hooks
