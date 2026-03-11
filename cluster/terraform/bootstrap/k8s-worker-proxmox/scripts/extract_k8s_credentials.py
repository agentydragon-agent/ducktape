#!/usr/bin/env python3
"""Extract K8s cluster credentials from a Talos control plane node.

Called by Terraform data "external" — reads query JSON on stdin, outputs
JSON on stdout.

Required env vars:
  CP_NODE       — IP or hostname of a Talos control plane node
  TALOSCONFIG   — path to talosconfig file
"""

import json
import os
import shutil
import subprocess
import sys

import yaml


def run_talosctl(*args: str) -> str:
    cp_node = os.environ["CP_NODE"]
    talosconfig = os.environ["TALOSCONFIG"]
    result = subprocess.run(
        ["talosctl", "-n", cp_node, "--talosconfig", talosconfig, *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def main() -> None:
    # Terraform data "external" sends query JSON on stdin — consume it.
    sys.stdin.read()

    for var in ("CP_NODE", "TALOSCONFIG"):
        if not os.environ.get(var):
            print(f"{var} env var required", file=sys.stderr)
            sys.exit(1)

    if not shutil.which("talosctl"):
        print("talosctl not found in PATH", file=sys.stderr)
        sys.exit(1)

    # Extract bootstrap kubeconfig (server URL is https://localhost:7445 —
    # kubespand's KubePrism LB proxies to API server).
    bootstrap_kubeconfig = run_talosctl("cat", "/etc/kubernetes/bootstrap-kubeconfig")

    # Extract CA certificate.
    ca_cert = run_talosctl("cat", "/etc/kubernetes/pki/ca.crt")

    # Extract cluster identity from the KubeSpan config resource.
    # This is a clean YAML resource with clusterId and sharedSecret.
    ks_yaml = run_talosctl("get", "kubespanconfig", "-o", "yaml")
    ks_config = yaml.safe_load(ks_yaml)
    cluster_id = ks_config["spec"]["clusterId"]
    cluster_secret = ks_config["spec"]["sharedSecret"]

    if not cluster_id:
        print("clusterId is empty in kubespanconfig", file=sys.stderr)
        sys.exit(1)
    if not cluster_secret:
        print("sharedSecret is empty in kubespanconfig", file=sys.stderr)
        sys.exit(1)

    json.dump(
        {
            "bootstrap_kubeconfig": bootstrap_kubeconfig,
            "ca_cert": ca_cert,
            "cluster_id": cluster_id,
            "cluster_secret": cluster_secret,
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
