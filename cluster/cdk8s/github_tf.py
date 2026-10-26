"""Shared artifact tree for the GitHub OpenTofu Workspaces."""

from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "github-tf"
OUTPUT_DIR = f"{GENERATED_ROOT}/{NAME}"
