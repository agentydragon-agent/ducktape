# Container E2E test image: python:3.13-slim + git + JDK (keytool).
#
# Pre-bakes dependencies that would be slow to install at test time.
# Built and pushed to GHCR by .github/workflows/e2e-container-image.yml.
# Pinned in MODULE.bazel via oci.pull and used by test_container_e2e.py.
FROM python:3.13-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        default-jdk-headless \
        git \
    && rm -rf /var/lib/apt/lists/*
