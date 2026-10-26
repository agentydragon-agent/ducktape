"""Artifact source for inline OpenTofu Workspaces under Forgejo."""

from cluster.cdk8s.manifest_roots import GENERATED_ROOT

NAME = "forgejo-gitops"
OUTPUT_DIR = f"{GENERATED_ROOT}/forgejo/gitops"
