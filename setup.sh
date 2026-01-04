#!/usr/bin/env bash
# Expects to run from repo root.
set -e

# Proxy & CA for APT
# Codex sets HTTP_PROXY / HTTPS_PROXY and PIP_CERT / NODE_EXTRA_CA_CERTS.
# We only need to teach APT to use the proxy, everything else (pip, curl…)
# respects hits it.
##############################################################################
[[ -n "${HTTP_PROXY:-}" ]] && echo "Acquire::http::Proxy  \"${HTTP_PROXY}\";" >/etc/apt/apt.conf.d/01proxy
[[ -n "${HTTPS_PROXY:-}" ]] && echo "Acquire::https::Proxy \"${HTTPS_PROXY}\";" >>/etc/apt/apt.conf.d/01proxy

# ── System packages ──────────────────────────────────────────────────────────
# Those won't work -- getting:
#   'Cannot initiate the connection to archive.ubuntu.com:80 (185.125.190.81). - connect (101: Network is unreachable)'
apt-get update -qq
apt-get install -y --no-install-recommends \
	build-essential python3-venv python3-dev curl ca-certificates

# Dev hygiene
##############################################################################
pip install pre-commit
pre-commit install --install-hooks
