"""Flux Build Validation Script.

Validates that Flux can build all kustomizations and analyzes the results.

Run via Bazel: bazel run //cluster/scripts:validate_flux_build
"""

from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

from cluster.scripts.runfiles_util import resolve_path

_FLUX_BIN = resolve_path("multitool/tools/flux/flux")


def run_flux_build() -> tuple[bool, str, str]:
    """Run flux build and capture output."""
    kustomization_file = Path("./k8s/flux-system/gotk-sync.yaml")

    if not kustomization_file.exists():
        return True, "", "flux-system not bootstrapped yet - skipping validation"

    result = subprocess.run(
        [
            _FLUX_BIN,
            "build",
            "kustomization",
            "flux-system",
            "--path",
            "./k8s",
            "--kustomization-file",
            kustomization_file,
            "--dry-run",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    return result.returncode == 0, result.stdout, result.stderr


def analyze_flux_output(output: str) -> list[str]:
    """Analyze the flux build output for potential issues."""
    warnings = []

    try:
        documents = list(yaml.safe_load_all(output))
        resource_counts: Counter[str] = Counter()
        namespaces = set()

        for doc in documents:
            if not doc:
                continue

            kind = doc.get("kind")
            if kind:
                resource_counts[kind] += 1

            namespace = doc.get("metadata", {}).get("namespace")
            if namespace:
                namespaces.add(namespace)

        if resource_counts.get("HelmRelease", 0) == 0:
            warnings.append("⚠️  No HelmRelease resources found - expected for GitOps deployment")

        if resource_counts.get("Kustomization", 0) == 0:
            warnings.append("⚠️  No Flux Kustomization resources found")

        external_secrets_count = 0
        for doc in documents:
            if doc and doc.get("kind") == "HelmRelease" and doc.get("metadata", {}).get("name") == "external-secrets":
                external_secrets_count += 1

        if external_secrets_count > 1:
            warnings.append(f"❌ Found {external_secrets_count} external-secrets HelmReleases (should be exactly 1)")
        elif external_secrets_count == 0:
            warnings.append("⚠️  No external-secrets HelmRelease found")

        total_resources = sum(resource_counts.values())
        if total_resources > 0:
            print(f"📊 Flux build generated {total_resources} resources across {len(namespaces)} namespaces")

            top_resources = sorted(resource_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            for resource_type, count in top_resources:
                print(f"   {resource_type}: {count}")

    except yaml.YAMLError as e:
        warnings.append(f"⚠️  Failed to parse flux build output as YAML: {e}")
    except Exception as e:
        warnings.append(f"⚠️  Error analyzing flux build output: {e}")

    return warnings


def main():
    """Main validation function."""
    print("🔧 Running flux build validation...")

    success, stdout, stderr = run_flux_build()

    if not success:
        print("❌ flux build failed:")
        if stderr:
            print(stderr)
        return 1

    if stderr and "skipping validation" in stderr:
        print(f"[INFO] {stderr}")
        return 0

    warnings = analyze_flux_output(stdout)

    if warnings:
        print("\nValidation warnings:")
        for warning in warnings:
            print(warning)

        error_count = sum(1 for w in warnings if w.startswith("❌"))
        if error_count > 0:
            return 1

    print("✅ Flux build validation passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
