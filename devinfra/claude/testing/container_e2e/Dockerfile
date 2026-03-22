# SUPERSEDED: This image is now built entirely in Bazel via rules_distroless.
# See BUILD.bazel (oci_image target) and bookworm_e2e.yaml (deb manifest).
# Kept as documentation of what the image contains.
#
# TODO: Eventually switch to the Claude Code web container RE (reverse-engineered
# container snapshot) so the E2E test exercises a realistic environment.
FROM python:3.13-slim

RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends \
        default-jdk-headless \
        git \
    && rm -rf /var/lib/apt/lists/*
