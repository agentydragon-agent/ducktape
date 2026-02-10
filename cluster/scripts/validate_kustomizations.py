"""Parallel kustomize validation script.

Validates all kustomizations quickly and quietly (unless errors occur).

Checks:
1. kustomize build succeeds for each kustomization
2. No duplicate external-secrets installations
3. CRD layering: HelmReleases are not mixed with CRD instances from external operators
4. Dependency graph: No circular dependencies, required dependencies present
5. Flux build: Validates flux can build the complete kustomization tree

See AGENTS.md section "Flux Kustomization Layering" for CRD layering details.

Run via Bazel: bazel run //cluster/scripts:validate_kustomizations
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from cluster.scripts.runfiles_util import resolve_path
from tools.env_utils import get_workspace_dir

logger = logging.getLogger(__name__)

_KUSTOMIZE_BIN = resolve_path("multitool/tools/kustomize/kustomize")
_FLUX_BIN = resolve_path("multitool/tools/flux/flux")


# Map CRD kinds to their operator Kustomization names
CRD_TO_OPERATOR: dict[str, str] = {
    # external-secrets-operator
    "ExternalSecret": "external-secrets-operator",
    "ClusterExternalSecret": "external-secrets-operator",
    "SecretStore": "external-secrets-operator",
    "ClusterSecretStore": "external-secrets-operator",
    "Password": "external-secrets-operator",
    "Fake": "external-secrets-operator",
    "VaultDynamicSecret": "external-secrets-operator",
    # cert-manager
    "Certificate": "cert-manager",
    "CertificateRequest": "cert-manager",
    "Issuer": "cert-manager",
    "ClusterIssuer": "cert-manager",
    # kyverno
    "ClusterPolicy": "kyverno",
    "Policy": "kyverno",
    # metallb
    "IPAddressPool": "metallb",
    "L2Advertisement": "metallb",
    "BGPAdvertisement": "metallb",
    # vault-operator
    "Vault": "vault-operator",
    # tofu-controller (in core)
    "Terraform": "core",
    # powerdns-operator
    "ClusterZone": "powerdns-operator",
    "ClusterRRset": "powerdns-operator",
}

# These Kustomizations ARE the operators, so they don't need to depend on themselves
OPERATOR_KUSTOMIZATIONS = {
    "external-secrets-operator",
    "external-secrets",  # config kustomization
    "cert-manager",
    "cert-manager-config",
    "cert-manager-trust",
    "cert-manager-environment",
    "kyverno",
    "kyverno-policies",
    "metallb",
    "metallb-config",
    "vault-operator",
    "vault",
    "core",
    "powerdns-operator",
    "cluster-ca",  # Uses cert-manager CRDs but is part of cert-manager layer
}


# ============================================================================
# Dependency Graph Validation (from validate_dependencies.py)
# ============================================================================


@dataclass
class DependsOn:
    name: str
    namespace: str | None = None


@dataclass
class KustomizationSpec:
    path: str
    depends_on: list[DependsOn]

    @classmethod
    def from_dict(cls, spec_dict: dict) -> KustomizationSpec:
        depends_on = []
        for dep in spec_dict.get("dependsOn", []):
            if isinstance(dep, dict) and dep.get("name"):
                depends_on.append(DependsOn(name=dep["name"], namespace=dep.get("namespace")))

        return cls(path=spec_dict.get("path", ""), depends_on=depends_on)


def load_kustomizations(root: Path) -> dict[str, KustomizationSpec]:
    """Load all Flux kustomizations from the repository."""
    kustomizations = {}

    for flux_kustomization_file in root.rglob("flux-kustomization.yaml"):
        with flux_kustomization_file.open() as f:
            docs = list(yaml.safe_load_all(f))
            for doc in docs:
                if (
                    doc
                    and doc.get("kind") == "Kustomization"
                    and doc.get("apiVersion", "").startswith("kustomize.toolkit.fluxcd.io")
                ):
                    name = doc.get("metadata", {}).get("name")
                    if name:
                        kustomizations[name] = KustomizationSpec.from_dict(doc.get("spec", {}))

    return kustomizations


def build_dependency_graph(kustomizations: dict[str, KustomizationSpec]) -> dict[str, list[str]]:
    """Build dependency graph from kustomizations."""
    graph: dict[str, list[str]] = defaultdict(list)

    for name, spec in kustomizations.items():
        depends_on = spec.depends_on
        for dep in depends_on:
            graph[dep.name].append(name)

    return dict(graph)


def find_cycles(graph: dict[str, list[str]], all_nodes: set[str]) -> list[list[str]]:
    """Find cycles in dependency graph using DFS."""
    # Node states for DFS traversal: unvisited, in-progress, done
    unvisited, in_progress, done = 0, 1, 2
    color = dict.fromkeys(all_nodes, unvisited)
    cycles = []

    def dfs(node: str, path: list[str]) -> None:
        if color[node] == in_progress:
            # Found cycle
            cycle_start = path.index(node)
            cycles.append([*path[cycle_start:], node])
            return

        if color[node] == done:
            return

        color[node] = in_progress
        path.append(node)

        for neighbor in graph.get(node, []):
            dfs(neighbor, path)

        path.pop()
        color[node] = done

    for node in all_nodes:
        if color[node] == unvisited:
            dfs(node, [])

    return cycles


def check_required_dependencies(kustomizations: dict[str, KustomizationSpec]) -> list[str]:
    """Check that critical dependencies are correctly set up."""
    errors = []

    # Define critical dependency rules
    dependency_rules = {
        "external-secrets-config": {
            "must_come_before": ["authentik", "gitea", "harbor", "powerdns", "matrix"],
            "reason": "Applications need external-secrets ClusterSecretStore to sync secrets from Vault",
        },
        "cert-manager": {
            "must_come_before": ["ingress-nginx", "authentik", "gitea", "harbor"],
            "reason": "TLS certificates required for ingress and applications",
        },
        "ingress-nginx": {
            "must_come_before": ["authentik", "gitea", "harbor", "matrix"],
            "reason": "Applications need ingress controller for external access",
        },
        "vault": {
            "must_come_before": ["external-secrets-operator", "external-secrets-config"],
            "reason": "Vault must be ready before external-secrets can connect",
        },
        "metallb-config": {
            "must_come_before": ["ingress-nginx"],
            "reason": "Load balancer needed for ingress controller",
        },
    }

    # Build reverse dependency lookup
    depends_on_map = {}
    for name, spec in kustomizations.items():
        depends_on_map[name] = [dep.name for dep in spec.depends_on]

    def has_dependency_path(from_kust: str, to_kust: str, visited: set[str] | None = None) -> bool:
        """Check if from_kust appears in the dependency tree of to_kust."""
        if visited is None:
            visited = set()

        if to_kust in visited:
            return False

        if from_kust == to_kust:
            return True

        visited.add(to_kust)

        return any(has_dependency_path(from_kust, dep, visited) for dep in depends_on_map.get(to_kust, []))

    # Check each dependency rule
    for prereq, rule in dependency_rules.items():
        if prereq not in kustomizations:
            continue

        for dependent in rule["must_come_before"]:
            if dependent not in kustomizations:
                continue

            # Check if dependent has prereq in its dependency chain
            if prereq not in depends_on_map.get(dependent, []):
                # Also check for transitive dependencies
                has_transitive_dep = False
                for dep in depends_on_map.get(dependent, []):
                    if has_dependency_path(prereq, dep):
                        has_transitive_dep = True
                        break

                if not has_transitive_dep:
                    errors.append(f"{dependent} should depend on {prereq} ({rule['reason']})")

    return errors


def validate_external_secrets_dependencies(kustomizations: dict[str, KustomizationSpec], k8s_dir: Path) -> list[str]:
    """Validate external-secrets specific dependency patterns."""
    errors = []

    # Check that services using ExternalSecret resources depend on external-secrets
    services_with_external_secrets = []

    for kust_file in k8s_dir.rglob("*.yaml"):
        if "flux-kustomization" in kust_file.name:
            continue

        try:
            with kust_file.open() as f:
                docs = list(yaml.safe_load_all(f))
                for doc in docs:
                    if (
                        doc
                        and doc.get("kind") == "ExternalSecret"
                        and doc.get("apiVersion", "").startswith("external-secrets.io")
                    ):
                        # Find which kustomization this belongs to
                        relative_path = kust_file.relative_to(k8s_dir)
                        service_name = relative_path.parts[0] if relative_path.parts else None
                        if service_name and service_name not in services_with_external_secrets:
                            services_with_external_secrets.append(service_name)
        except yaml.YAMLError as e:
            # YAML files might contain Go templating - warn but continue
            print(f"Warning: Failed to parse {kust_file}: {e}", file=sys.stderr)
            continue

    # Check dependencies
    for service in services_with_external_secrets:
        if service in kustomizations:
            deps = [dep.name for dep in kustomizations[service].depends_on]
            if "external-secrets-config" not in deps:
                errors.append(f"{service} uses ExternalSecret resources but doesn't depend on external-secrets-config")

    return errors


def validate_dependencies(k8s_dir: Path) -> list[str]:
    """Validate GitOps dependency graph. Returns list of errors."""
    errors = []

    kustomizations = load_kustomizations(k8s_dir)

    if not kustomizations:
        errors.append("No Flux kustomizations found")
        return errors

    # Build dependency graph
    graph = build_dependency_graph(kustomizations)
    all_nodes = set(kustomizations.keys()) | set().union(*graph.values())

    # Check for circular dependencies
    cycles = find_cycles(graph, all_nodes)
    if cycles:
        for cycle in cycles:
            errors.append(f"Circular dependency: {' → '.join(cycle)}")

    # Check required dependencies
    errors.extend(check_required_dependencies(kustomizations))

    # Check external-secrets specific dependencies
    errors.extend(validate_external_secrets_dependencies(kustomizations, k8s_dir))

    return errors


# ============================================================================
# Flux Build Validation (from validate_flux_build.py)
# ============================================================================


def run_flux_build(k8s_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run flux build and return the result.

    Raises:
        FileNotFoundError: If gotk-sync.yaml is not found.
    """
    kustomization_file = k8s_dir / "flux-system" / "gotk-sync.yaml"

    if not kustomization_file.exists():
        raise FileNotFoundError(f"gotk-sync.yaml not found at {kustomization_file}")

    result = subprocess.run(
        [
            _FLUX_BIN,
            "build",
            "kustomization",
            "flux-system",
            "--path",
            k8s_dir,
            "--kustomization-file",
            kustomization_file,
            "--dry-run",
            "--verbose",  # Required to print generated objects to stdout
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.stdout:
        logger.debug("flux build stdout:\n%s", result.stdout)
    if result.stderr:
        logger.debug("flux build stderr:\n%s", result.stderr)

    return result


def analyze_flux_output(output: str) -> list[str]:
    """Analyze the flux build output for potential issues.

    Note: flux build kustomization outputs Flux Kustomization CRs (orchestrators),
    NOT the nested HelmReleases. HelmReleases are validated separately by our
    kustomize build checks on individual directories.
    """
    errors = []

    documents = list(yaml.safe_load_all(output))
    resource_counts: Counter[str] = Counter()

    for doc in documents:
        if not doc:
            continue

        kind = doc.get("kind")
        if kind:
            resource_counts[kind] += 1

    # We expect Flux Kustomization CRs and GitRepository in the flux build output
    if resource_counts.get("Kustomization", 0) == 0:
        errors.append("No Flux Kustomization resources found in flux build output")

    if resource_counts.get("GitRepository", 0) == 0:
        errors.append("No GitRepository resource found in flux build output")

    return errors


def validate_flux_build(k8s_dir: Path) -> list[str]:
    """Validate flux build. Returns list of errors."""
    try:
        result = run_flux_build(k8s_dir)
    except FileNotFoundError as e:
        return [str(e)]

    if result.returncode != 0:
        return [f"flux build failed:\nk8s_dir: {k8s_dir}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"]

    if not result.stdout.strip():
        return [f"flux build returned empty output:\nk8s_dir: {k8s_dir}\nstderr: {result.stderr.strip() or 'none'}"]

    return analyze_flux_output(result.stdout)


# ============================================================================
# CRD Layering Validation
# ============================================================================


def check_crd_layering(kustomization_path: Path, output: str) -> list[str]:
    """Check if a kustomization mixes HelmReleases with CRD instances from external operators.

    Returns list of error messages (empty if valid).
    """
    kust_name = kustomization_path.parent.name

    # Skip operator kustomizations - they define/configure the CRDs
    # Check all ancestor directories (handles base/overlays nesting)
    if any(part in OPERATOR_KUSTOMIZATIONS for part in kustomization_path.parent.parts):
        return []

    # Skip overlay directories (base handles the check)
    if "overlays" in kustomization_path.parts:
        return []

    has_helmrelease = False
    crd_instances: list[tuple[str, str]] = []  # (kind, operator)

    documents = list(yaml.safe_load_all(output))
    for doc in documents:
        if not doc:
            continue
        kind = doc.get("kind", "")

        if kind == "HelmRelease":
            has_helmrelease = True

        if kind in CRD_TO_OPERATOR:
            operator = CRD_TO_OPERATOR[kind]
            crd_instances.append((kind, operator))

    errors = []
    if has_helmrelease and crd_instances:
        # Deduplicate for cleaner output
        unique_crds = sorted({f"{k} (needs {op})" for k, op in crd_instances})
        errors.append(
            f"CRD layering violation: Mixes HelmRelease with CRD instances: {', '.join(unique_crds)}. "
            f"Split CRD instances into a separate '{kust_name}-secrets/' Kustomization. "
            f"See AGENTS.md 'Flux Kustomization Layering'."
        )

    return errors


# ============================================================================
# Kustomize Build Validation
# ============================================================================


async def validate_kustomization(kustomization_path: Path) -> tuple[Path, bool, str]:
    """Validate a single kustomization directory."""
    try:
        proc = await asyncio.create_subprocess_exec(
            _KUSTOMIZE_BIN,
            "build",
            kustomization_path.parent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return kustomization_path, True, stdout.decode()
        return kustomization_path, False, stderr.decode()
    except Exception as e:
        return kustomization_path, False, str(e)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Validate kustomizations in parallel")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show successful validations")
    parser.add_argument("--root", type=Path, help="Root directory to search for kustomizations")
    parser.add_argument(
        "--format", choices=["human", "json"], default="human", help="Output format (human or json for Terraform)"
    )
    parser.add_argument(
        "--skip-flux-build",
        action="store_true",
        help="Skip flux build validation (useful when flux-system not bootstrapped)",
    )
    parser.add_argument("--skip-dependencies", action="store_true", help="Skip dependency graph validation")
    args = parser.parse_args()

    # Find all kustomization.yaml files (excluding flux-system)
    root = args.root or (get_workspace_dir() / "cluster" / "k8s")
    kustomizations = []

    for kustomization_file in root.rglob("kustomization.yaml"):
        if "flux-system" not in kustomization_file.parts:
            kustomizations.append(kustomization_file)

    if not kustomizations:
        print(f"No kustomizations found in {root}")
        return 0

    # Validate all kustomizations in parallel
    tasks = [validate_kustomization(k) for k in kustomizations]
    results = await asyncio.gather(*tasks)

    # Process results
    successful = []
    kust_errors: list[tuple[Path, str]] = []  # Errors tied to specific kustomization paths
    global_errors: list[str] = []  # Validation errors not tied to a specific path
    kustomize_outputs = {}

    for kustomization, success, output in results:
        if success:
            successful.append(kustomization)
            kustomize_outputs[kustomization] = output
        else:
            kust_errors.append((kustomization, output))

    # Check for duplicate external-secrets installations
    external_secrets_deployments: dict[str, list[str]] = defaultdict(list)

    for kustomization, output in kustomize_outputs.items():
        documents = yaml.safe_load_all(output)
        for doc in documents:
            if doc and doc.get("kind") == "HelmRelease" and doc.get("metadata", {}).get("name") == "external-secrets":
                namespace = doc.get("metadata", {}).get("namespace", "default")
                chart_version = doc.get("spec", {}).get("chart", {}).get("spec", {}).get("version", "unknown")
                external_secrets_deployments[f"{namespace}/{chart_version}"].append(str(kustomization.parent))

    # Validate exactly one external-secrets installation
    if len(external_secrets_deployments) > 1:
        global_errors.append("Multiple external-secrets HelmRelease found:")
        for deployment, paths in external_secrets_deployments.items():
            global_errors.append(f"  {deployment}: {', '.join(paths)}")
        global_errors.append("There should be exactly ONE external-secrets installation.")
    elif len(external_secrets_deployments) == 0:
        global_errors.append("No external-secrets HelmRelease found. At least one is required.")

    # Check CRD layering violations
    for kustomization, output in kustomize_outputs.items():
        crd_errors = check_crd_layering(kustomization, output)
        for error in crd_errors:
            kust_errors.append((kustomization, error))

    # Validate dependency graph
    if not args.skip_dependencies:
        global_errors.extend(validate_dependencies(root))

    # Validate flux build
    if not args.skip_flux_build:
        global_errors.extend(validate_flux_build(root))

    has_errors = bool(kust_errors or global_errors)

    # Output results
    if args.format == "json":
        # JSON output for Terraform data source
        if has_errors:
            error_details = [{"path": str(k.parent), "error": error.strip()} for k, error in kust_errors]
            error_details.extend([{"path": "", "error": error.strip()} for error in global_errors])
            result = {"error": f"Validation failed with {len(error_details)} errors", "details": error_details}
            print(json.dumps(result), file=sys.stderr)
            return 1
        result = {"status": "passed", "validated_count": str(len(successful))}
        print(json.dumps(result))
        return 0

    # Human-readable output
    if args.verbose and successful:
        print(f"✅ Successfully validated {len(successful)} kustomizations:")
        for k in successful:
            print(f"  {k.parent}")

    if has_errors:
        print("❌ Validation failed:")
        for kustomization, error in kust_errors:
            print(f"  {kustomization.parent}:")
            print(f"    {error.strip()}")
        for error in global_errors:
            print(f"  {error.strip()}")
        return 1

    if not args.verbose:
        print(f"✅ All {len(successful)} kustomizations valid, no dependency/layering issues")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
