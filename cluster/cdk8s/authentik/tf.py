"""Artifact source for the inline OpenTofu Workspaces under Authentik."""

from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "authentik-tf"
OUTPUT_DIR = f"{GENERATED_ROOT}/authentik/tf"
