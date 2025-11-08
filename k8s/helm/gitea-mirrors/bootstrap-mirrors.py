#!/usr/bin/env python3
"""Apply GiteaMirror CRDs to cluster from values.yaml."""

from pathlib import Path
import subprocess
import sys

import yaml


def load_mirrors_from_values():
    """Load mirror configuration from values.yaml."""
    values_path = Path(__file__).parent / "values.yaml"
    with values_path.open() as f:
        values = yaml.safe_load(f)
    return values.get("mirrors", []), values.get("global", {})


def derive_mirror_name(url: str) -> str:
    """Derive repository name from URL."""
    import re

    # Remove protocol
    url = re.sub(r"^https?://", "", url)
    # Remove common git hosts
    url = re.sub(r"^(github\.com|gitlab\.com|bitbucket\.org)/", "", url)
    # Replace slashes with dashes
    url = url.replace("/", "-")
    # Remove .git suffix
    url = re.sub(r"\.git$", "", url)
    return url.lower()


def create_mirror_manifest(url: str, interval: str, namespace: str = "gitea") -> dict:
    """Create a GiteaMirror manifest."""
    name = derive_mirror_name(url)
    return {
        "apiVersion": "gitea.io/v1alpha1",
        "kind": "GiteaMirror",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"url": url, "interval": interval},
    }


def apply_manifest(manifest: dict):
    """Apply a manifest to the cluster using kubectl."""
    yaml_content = yaml.dump(manifest)

    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=yaml_content,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        print(f"Error applying manifest: {result.stderr}")
        return False

    return True


def main():
    """Main function to apply all mirror CRDs."""
    mirrors, global_config = load_mirrors_from_values()
    interval = global_config.get("syncInterval", "6h")

    print(f"Applying {len(mirrors)} GiteaMirror resources...")

    success_count = 0
    failed_count = 0

    for mirror in mirrors:
        url = mirror["url"]
        name = derive_mirror_name(url)

        print(f"Creating GiteaMirror: {name}")
        manifest = create_mirror_manifest(url, interval)

        if apply_manifest(manifest):
            print(f"  ✓ Applied {name}")
            success_count += 1
        else:
            print(f"  ✗ Failed to apply {name}")
            failed_count += 1

    print(f"\nSummary: {success_count} successful, {failed_count} failed")

    if failed_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
