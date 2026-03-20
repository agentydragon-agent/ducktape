# Container E2E test image: python:3.13-slim + git + JDK (keytool).
#
# Pre-bakes dependencies that would be slow to install at test time.
# Built and pushed to GHCR by .github/workflows/e2e-container-image.yml.
# Pinned in MODULE.bazel via oci.pull and used by test_container_e2e.py.
#
# TODO: Unify this with the Claude Code web container RE (reverse-engineered
# container snapshot). This should eventually match the actual Claude Code web
# container image so the E2E test exercises a realistic environment.
FROM python:3.13-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        default-jdk-headless \
        git \
    && rm -rf /var/lib/apt/lists/*
