"""Layered Talos cluster bootstrap.

This is the ONLY supported way to bootstrap the cluster.
Run via: bazel run //cluster:bootstrap

Multi-layer deployment with persistent auth separation:
  Layer 0: Persistent Auth (CSI tokens, sealed secrets keypair)
  Layer 1: Infrastructure (VMs, Talos, CNI, networking)
  Layer 2: Services (Deploy via GitOps - Flux handles DNS/SSO automatically)
"""

import argparse
import json
import logging
import os
import subprocess
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.stream import stream
from tenacity import Retrying, retry_if_result, stop_after_delay, wait_fixed

from bazel_util.workspace import get_build_workspace_directory
from cluster.scripts.runfiles_util import resolve_path

_TOFU_BIN = resolve_path("multitool/tools/tofu/tofu")


SCRIPT_DIR = get_build_workspace_directory() / "cluster"
TERRAFORM_DIR = SCRIPT_DIR / "terraform"

logging.basicConfig(format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S", level=logging.INFO)
log = logging.getLogger(__name__)


class Layer(IntEnum):
    PERSISTENT_AUTH = 0
    INFRASTRUCTURE = 1
    SERVICES = 2

    @property
    def tf_dir_name(self) -> str:
        return ["00-persistent-auth", "01-infrastructure", "02-services"][self.value]

    @property
    def tf_dir(self) -> Path:
        return TERRAFORM_DIR / self.tf_dir_name


def run(
    cmd: list[str | Path],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=check, timeout=timeout, capture_output=capture, text=capture)


def tofu(layer: Layer, *args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return run([_TOFU_BIN, *args], cwd=layer.tf_dir, timeout=timeout)


def tofu_output(layer: Layer, name: str) -> str:
    result = run([_TOFU_BIN, "output", "-raw", name], cwd=layer.tf_dir, capture=True)
    return result.stdout.strip()


def tofu_state_has_resources(layer: Layer) -> bool:
    result = run([_TOFU_BIN, "show", "-json"], cwd=layer.tf_dir, capture=True, check=False)
    if result.returncode != 0:
        return False
    resources = json.loads(result.stdout).get("values", {}).get("root_module", {}).get("resources", [])
    return len(resources) > 0


def parse_json_objects(text: str) -> list[dict]:
    """Parse concatenated JSON objects (talosctl -o json output)."""
    decoder = json.JSONDecoder()
    results = []
    idx = 0
    text = text.strip()
    while idx < len(text):
        try:
            obj, end_idx = decoder.raw_decode(text, idx)
            results.append(obj)
            idx = end_idx
        except json.JSONDecodeError:
            idx += 1
    return results


def preflight(root: Path) -> None:
    log.info("Phase 0: Preflight Validation")

    result = run(["git", "diff-index", "--quiet", "HEAD", "--", "cluster/"], cwd=root, check=False)
    if result.returncode != 0:
        raise SystemExit("Git working tree is not clean in cluster/. Commit or stash changes before bootstrap.")

    log.info("Running pre-commit validation on cluster files...")
    cluster_files_result = run(["git", "ls-files", "--", "cluster/"], cwd=root, capture=True)
    files = cluster_files_result.stdout.strip().split("\n")
    run(["pre-commit", "run", "--files", *files], cwd=root)

    for layer in Layer:
        log.info("Validating terraform layer: %s", layer.tf_dir_name)
        tofu(layer, "validate")


def deploy_persistent_auth() -> None:
    log.info("Layer 0: Persistent Auth Setup")

    layer = Layer.PERSISTENT_AUTH
    state = layer.tf_dir / "terraform.tfstate"
    if state.exists() and tofu_state_has_resources(layer):
        log.info("Persistent auth already exists - skipping")
        return

    log.info("Deploying persistent auth layer...")
    tofu(layer, "apply", "-auto-approve")
    log.info("Persistent auth layer ready")


def deploy_infrastructure() -> None:
    log.info("Layer 1: Infrastructure Deployment")
    log.info("Deploying infrastructure (VMs, Talos, Cilium, sealed-secrets)...")
    tofu(Layer.INFRASTRUCTURE, "apply", "-auto-approve")

    kubeconfig = Layer.INFRASTRUCTURE.tf_dir / "kubeconfig"
    os.environ["KUBECONFIG"] = str(kubeconfig)

    config.load_kube_config(kubeconfig)
    v1 = client.CoreV1Api()

    log.info("Verifying cluster access...")
    version = client.VersionApi().get_code()
    log.info("Kubernetes %s.%s", version.major, version.minor)
    for node in v1.list_node().items:
        conditions = node.status.conditions or []
        ready = any(c.type == "Ready" and c.status == "True" for c in conditions)
        log.info("  %s: %s", node.metadata.name, "Ready" if ready else "NotReady")

    # API servers are static pods started before Cilium — their sockets were created
    # without BPF interception. Restarting Cilium forces re-attachment of BPF programs
    # to all processes, fixing ClusterIP routing for webhooks.
    log.info("Restarting Cilium to refresh BPF state for API servers...")
    apps_v1 = client.AppsV1Api()
    apps_v1.patch_namespaced_daemon_set(
        "cilium",
        "kube-system",
        {
            "spec": {
                "template": {
                    "metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat()}}
                }
            }
        },
    )

    _wait_for_daemonset_rollout(apps_v1, "cilium", "kube-system")
    log.info("Cilium restarted, BPF state refreshed")

    wait_for_convergence(v1)
    log.info("Infrastructure layer ready")


def _check_daemonset_ready(apps_v1: client.AppsV1Api, name: str, namespace: str) -> bool:
    ds = apps_v1.read_namespaced_daemon_set_status(name, namespace)
    desired = ds.status.desired_number_scheduled or 0
    updated = ds.status.updated_number_scheduled or 0
    available = ds.status.number_available or 0
    unavailable = ds.status.number_unavailable or 0
    return updated >= desired and unavailable == 0 and available >= desired


def _wait_for_daemonset_rollout(
    apps_v1: client.AppsV1Api, name: str, namespace: str, timeout: int = 300, interval: int = 5
) -> None:
    Retrying(stop=stop_after_delay(timeout), wait=wait_fixed(interval), retry=retry_if_result(lambda ready: not ready))(
        _check_daemonset_ready, apps_v1, name, namespace
    )


def wait_for_convergence(v1: client.CoreV1Api, timeout: int = 600, interval: int = 15) -> None:
    """Wait for cross-node networking to converge.

    During bootstrap, KubeSpan WireGuard tunnels take time to stabilize due to
    dual-identity from ISO-to-disk reboot (phantom peers persist for ~30 min TTL).
    Deploying webhook-based services (kyverno) before tunnels converge causes
    webhook timeout failures from API servers that can't reach webhook pods.
    See: investigations/2026-02-11-bootstrap-cross-node-and-kyverno/diary.md
    """
    log.info("Waiting for cross-node networking to converge...")

    talosconfig = Layer.INFRASTRUCTURE.tf_dir / "talosconfig.yml"
    bootstrap_ip = tofu_output(Layer.INFRASTRUCTURE, "bootstrap_node_ip")
    expected_peers = int(tofu_output(Layer.INFRASTRUCTURE, "expected_node_count")) - 1

    Retrying(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        retry=retry_if_result(lambda converged: not converged),
    )(_check_convergence, v1, bootstrap_ip, talosconfig, expected_peers)

    log.info("Cross-node networking converged")


def _check_convergence(v1: client.CoreV1Api, bootstrap_ip: str, talosconfig: Path, expected_peers: int) -> bool:
    """Check KubeSpan peers and Cilium health, return True when converged."""
    result = run(
        ["talosctl", "-n", bootstrap_ip, "--talosconfig", talosconfig, "get", "kubespanpeerstatuses", "-o", "json"],
        capture=True,
        check=False,
    )
    peers = parse_json_objects(result.stdout) if result.returncode == 0 else []
    up_count = sum(1 for p in peers if p.get("spec", {}).get("state") == "up")
    cilium_ok = _check_cilium_health(v1)

    if up_count < expected_peers or not cilium_ok:
        log.info(
            "  KubeSpan: %d/%d peers up (need %d), Cilium healthy: %s", up_count, len(peers), expected_peers, cilium_ok
        )
        return False
    return True


def _check_cilium_health(v1: client.CoreV1Api) -> bool:
    """Check Cilium health by execing into a cilium pod."""
    pods = v1.list_namespaced_pod("kube-system", label_selector="k8s-app=cilium")
    if not pods.items:
        return False
    try:
        health = stream(
            v1.connect_get_namespaced_pod_exec,
            pods.items[0].metadata.name,
            "kube-system",
            command=["cilium-health", "status"],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
        )
    except ApiException:
        return False
    return "OK" in health and not any(bad in health for bad in ("unreachable", "refused", "timeout"))


def deploy_services() -> None:
    log.info("Layer 2: Services")

    kubeconfig = Layer.INFRASTRUCTURE.tf_dir / "kubeconfig"
    os.environ.setdefault("KUBECONFIG", str(kubeconfig))

    log.info("Deploying services (Flux, Authentik, PowerDNS, Harbor, Gitea, Matrix)...")
    tofu(Layer.SERVICES, "apply", "-auto-approve")

    log.info("Bootstrap complete - Flux is now reconciling kustomizations.")
    print(f"\nAccess cluster: export KUBECONFIG='{kubeconfig}'")
    print("\nMonitor convergence:")
    print("   kubectl get kustomizations -A")
    print("   kubectl get pods -A | grep -v Running")


def main() -> None:
    parser = argparse.ArgumentParser(description="Layered Talos cluster bootstrap")
    parser.add_argument(
        "--start-from", choices=["infrastructure", "services"], help="Skip earlier layers, start from specified layer"
    )
    args = parser.parse_args()

    # Fix pre-commit/pip compatibility with Nix
    os.environ["PIP_USER"] = "false"
    os.environ["PRE_COMMIT_USE_UV"] = "1"

    root = SCRIPT_DIR.parent

    start_layer = {"infrastructure": Layer.INFRASTRUCTURE, "services": Layer.SERVICES}.get(
        args.start_from, Layer.PERSISTENT_AUTH
    )

    if start_layer > Layer.PERSISTENT_AUTH:
        log.info("Starting from layer: %s", args.start_from)

    preflight(root)

    if start_layer <= Layer.PERSISTENT_AUTH:
        deploy_persistent_auth()

    if start_layer <= Layer.INFRASTRUCTURE:
        deploy_infrastructure()

    deploy_services()


if __name__ == "__main__":
    main()
