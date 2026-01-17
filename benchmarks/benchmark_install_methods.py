#!/usr/bin/env python3
"""Benchmark cluster_tools installation methods.

Compares:
1. Manual binary download (as done in session start hook)
2. Nix with Cachix caches

Usage:
    python benchmarks/benchmark_install_methods.py [--nix-only] [--manual-only]

Requirements:
- For Nix benchmark: Nix must NOT be installed (script will install it)
- For clean benchmarks, run in a fresh environment (e.g., container)
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Tool versions - matching cluster_tools.py
OPENTOFU_VERSION = "1.9.0"
TFLINT_VERSION = "0.53.0"
FLUX_VERSION = "2.4.0"
KUSTOMIZE_VERSION = "5.5.0"
KUBESEAL_VERSION = "0.27.3"
HELM_VERSION = "3.16.4"


@dataclass
class TimingResult:
    """Timing result for a single operation."""

    operation: str
    duration_seconds: float
    success: bool
    details: str = ""


@dataclass
class BenchmarkResults:
    """Results from a benchmark run."""

    method: str
    total_seconds: float
    operations: list[TimingResult] = field(default_factory=list)

    def add(self, operation: str, duration: float, success: bool, details: str = "") -> None:
        self.operations.append(TimingResult(operation, duration, success, details))

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "total_seconds": self.total_seconds,
            "operations": [
                {
                    "operation": op.operation,
                    "duration_seconds": op.duration_seconds,
                    "success": op.success,
                    "details": op.details,
                }
                for op in self.operations
            ],
        }


def get_arch() -> str:
    """Get normalized architecture name."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(f"Unsupported architecture: {machine}")


def download_and_extract(url: str, binary_name: str, dest_path: Path) -> bool:
    """Download archive, extract binary, and install to dest_path."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            archive_path = tmppath / "archive"

            with urllib.request.urlopen(url, timeout=120) as response:
                archive_path.write_bytes(response.read())

            extract_dir = tmppath / "extracted"
            extract_dir.mkdir()

            if url.endswith((".tar.gz", ".tgz")):
                with tarfile.open(archive_path, "r:gz") as tar:
                    tar.extractall(extract_dir)
            elif url.endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    zf.extractall(extract_dir)
            else:
                print(f"  Unknown archive format: {url}")
                return False

            binary_path = None
            for path in extract_dir.rglob(binary_name):
                if path.is_file():
                    binary_path = path
                    break

            if not binary_path:
                for path in extract_dir.iterdir():
                    if path.is_file() and not path.suffix:
                        binary_path = path
                        break

            if not binary_path:
                print(f"  Could not find {binary_name} in archive")
                return False

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary_path, dest_path)
            dest_path.chmod(dest_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            return True

    except Exception as e:
        print(f"  Error: {e}")
        return False


def benchmark_manual_download(tools_dir: Path) -> BenchmarkResults:
    """Benchmark manual binary download method."""
    print("\n=== Benchmarking Manual Download Method ===\n")
    results = BenchmarkResults(method="manual_download", total_seconds=0)
    arch = get_arch()

    tools = [
        (
            "opentofu",
            "tofu",
            f"https://github.com/opentofu/opentofu/releases/download/v{OPENTOFU_VERSION}/tofu_{OPENTOFU_VERSION}_linux_{arch}.zip",
        ),
        (
            "tflint",
            "tflint",
            f"https://github.com/terraform-linters/tflint/releases/download/v{TFLINT_VERSION}/tflint_linux_{arch}.zip",
        ),
        (
            "flux",
            "flux",
            f"https://github.com/fluxcd/flux2/releases/download/v{FLUX_VERSION}/flux_{FLUX_VERSION}_linux_{arch}.tar.gz",
        ),
        (
            "kustomize",
            "kustomize",
            f"https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv{KUSTOMIZE_VERSION}/kustomize_v{KUSTOMIZE_VERSION}_linux_{arch}.tar.gz",
        ),
        (
            "kubeseal",
            "kubeseal",
            f"https://github.com/bitnami-labs/sealed-secrets/releases/download/v{KUBESEAL_VERSION}/kubeseal-{KUBESEAL_VERSION}-linux-{arch}.tar.gz",
        ),
        ("helm", "helm", f"https://get.helm.sh/helm-v{HELM_VERSION}-linux-{arch}.tar.gz"),
    ]

    total_start = time.perf_counter()

    for name, binary, url in tools:
        print(f"Installing {name}...")
        start = time.perf_counter()
        success = download_and_extract(url, binary, tools_dir / binary)
        duration = time.perf_counter() - start
        results.add(name, duration, success, url)
        status = "OK" if success else "FAILED"
        print(f"  {status} in {duration:.2f}s")

    results.total_seconds = time.perf_counter() - total_start
    print(f"\nTotal time: {results.total_seconds:.2f}s")
    return results


def check_nix_installed() -> bool:
    """Check if Nix is installed."""
    return shutil.which("nix") is not None


def install_nix() -> tuple[float, bool]:
    """Install Nix using the official installer.

    Returns (duration_seconds, success).
    """
    print("Installing Nix...")
    start = time.perf_counter()

    try:
        # Use the determinate systems installer for better experience
        # It's faster and handles more edge cases
        result = subprocess.run(
            [
                "bash",
                "-c",
                "curl --proto '=https' --tlsv1.2 -sSf -L https://install.determinate.systems/nix | sh -s -- install --no-confirm",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )
        duration = time.perf_counter() - start

        if result.returncode != 0:
            print(f"  Nix installation failed: {result.stderr}")
            return duration, False

        return duration, True
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        print("  Nix installation timed out")
        return duration, False
    except Exception as e:
        duration = time.perf_counter() - start
        print(f"  Nix installation error: {e}")
        return duration, False


def setup_cachix() -> tuple[float, bool]:
    """Configure Cachix caches for Nix.

    Returns (duration_seconds, success).
    """
    print("Configuring Cachix caches...")
    start = time.perf_counter()

    # Create nix config directory if needed
    nix_conf_dir = Path.home() / ".config" / "nix"
    nix_conf_dir.mkdir(parents=True, exist_ok=True)

    # Write nix.conf with cachix caches
    nix_conf = nix_conf_dir / "nix.conf"
    nix_conf.write_text("""\
experimental-features = nix-command flakes
substituters = https://cache.nixos.org https://devenv.cachix.org https://nix-community.cachix.org
trusted-public-keys = cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY= devenv.cachix.org-1:w1cLUi8dv3hnoSPGAuibQv+f9TZLr6cv/Hm9XgU50cw= nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs=
""")

    duration = time.perf_counter() - start
    return duration, True


def benchmark_nix_install_tools(nix_path: str | None = None) -> BenchmarkResults:
    """Benchmark Nix-based tool installation."""
    print("\n=== Benchmarking Nix Method ===\n")
    results = BenchmarkResults(method="nix_cachix", total_seconds=0)

    total_start = time.perf_counter()

    # Step 1: Check/Install Nix
    if check_nix_installed():
        print("Nix already installed, skipping installation timing")
        results.add("nix_install", 0, True, "already_installed")
    else:
        duration, success = install_nix()
        results.add("nix_install", duration, success)
        if not success:
            results.total_seconds = time.perf_counter() - total_start
            return results

    # Reload PATH to pick up nix
    nix_bin = Path.home() / ".nix-profile" / "bin"
    nix_daemon_bin = Path("/nix/var/nix/profiles/default/bin")

    # Find nix binary
    nix_cmd = None
    for candidate in [nix_bin / "nix", nix_daemon_bin / "nix", shutil.which("nix")]:
        if candidate and Path(candidate).exists():
            nix_cmd = str(candidate)
            break

    if not nix_cmd:
        # Try sourcing nix profile
        result = subprocess.run(
            [
                "bash",
                "-c",
                "source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh 2>/dev/null || source ~/.nix-profile/etc/profile.d/nix.sh 2>/dev/null; which nix",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            nix_cmd = result.stdout.strip()

    if not nix_cmd:
        print("  Could not find nix after installation")
        results.add("nix_locate", 0, False, "nix binary not found")
        results.total_seconds = time.perf_counter() - total_start
        return results

    print(f"Using nix at: {nix_cmd}")

    # Step 2: Configure Cachix
    duration, success = setup_cachix()
    results.add("cachix_config", duration, success)

    # Step 3: Install tools via nix profile or nix-shell
    # Using nix profile install for individual packages
    tools = [
        ("opentofu", "nixpkgs#opentofu"),
        ("tflint", "nixpkgs#tflint"),
        ("flux", "nixpkgs#fluxcd"),
        ("kustomize", "nixpkgs#kustomize"),
        ("kubeseal", "nixpkgs#kubeseal"),
        ("helm", "nixpkgs#kubernetes-helm"),
    ]

    # Create a shell command that sources nix properly
    nix_source = """
    if [ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]; then
        source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
    elif [ -f ~/.nix-profile/etc/profile.d/nix.sh ]; then
        source ~/.nix-profile/etc/profile.d/nix.sh
    fi
    """

    for name, pkg in tools:
        print(f"Installing {name} via Nix...")
        start = time.perf_counter()

        try:
            # Use nix profile install
            cmd = f"{nix_source}; nix profile install {pkg} --accept-flake-config"
            result = subprocess.run(
                ["bash", "-c", cmd],
                check=False,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout per tool
            )
            duration = time.perf_counter() - start
            success = result.returncode == 0

            if not success:
                # Try alternative: nix-env
                cmd = f"{nix_source}; nix-env -iA nixpkgs.{name.replace('-', '_')}"
                result = subprocess.run(["bash", "-c", cmd], check=False, capture_output=True, text=True, timeout=300)
                duration = time.perf_counter() - start
                success = result.returncode == 0

            results.add(name, duration, success, result.stderr if not success else "")
            status = "OK" if success else "FAILED"
            print(f"  {status} in {duration:.2f}s")

        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - start
            results.add(name, duration, False, "timeout")
            print(f"  TIMEOUT after {duration:.2f}s")
        except Exception as e:
            duration = time.perf_counter() - start
            results.add(name, duration, False, str(e))
            print(f"  ERROR: {e}")

    results.total_seconds = time.perf_counter() - total_start
    print(f"\nTotal time: {results.total_seconds:.2f}s")
    return results


def benchmark_nix_shell_all() -> BenchmarkResults:
    """Benchmark installing all tools at once via nix-shell."""
    print("\n=== Benchmarking Nix Shell (All at Once) ===\n")
    results = BenchmarkResults(method="nix_shell_all", total_seconds=0)

    total_start = time.perf_counter()

    # Check Nix is available
    if not check_nix_installed():
        print("Nix not installed, cannot run this benchmark")
        results.add("check_nix", 0, False, "nix not installed")
        return results

    nix_source = """
    if [ -f /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh ]; then
        source /nix/var/nix/profiles/default/etc/profile.d/nix-daemon.sh
    elif [ -f ~/.nix-profile/etc/profile.d/nix.sh ]; then
        source ~/.nix-profile/etc/profile.d/nix.sh
    fi
    """

    # Install all tools in one nix-shell command
    print("Installing all tools via nix-shell...")
    start = time.perf_counter()

    packages = "opentofu tflint fluxcd kustomize kubeseal kubernetes-helm"
    cmd = (
        f"{nix_source}; nix-shell -p {packages} --run 'echo Tools available: tofu tflint flux kustomize kubeseal helm'"
    )

    try:
        result = subprocess.run(["bash", "-c", cmd], check=False, capture_output=True, text=True, timeout=600)
        duration = time.perf_counter() - start
        success = result.returncode == 0
        results.add("nix_shell_all", duration, success, result.stdout + result.stderr)
        status = "OK" if success else "FAILED"
        print(f"  {status} in {duration:.2f}s")

    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        results.add("nix_shell_all", duration, False, "timeout")
        print(f"  TIMEOUT after {duration:.2f}s")

    results.total_seconds = time.perf_counter() - total_start
    print(f"\nTotal time: {results.total_seconds:.2f}s")
    return results


def print_comparison(results: list[BenchmarkResults]) -> None:
    """Print comparison table of results."""
    print("\n" + "=" * 60)
    print("BENCHMARK COMPARISON")
    print("=" * 60)

    for r in results:
        print(f"\n{r.method}:")
        print(f"  Total time: {r.total_seconds:.2f}s")
        print("  Operations:")
        for op in r.operations:
            status = "OK" if op.success else "FAILED"
            print(f"    {op.operation}: {op.duration_seconds:.2f}s [{status}]")

    print("\n" + "-" * 60)
    print("SUMMARY:")
    for r in results:
        successful_ops = sum(1 for op in r.operations if op.success)
        total_ops = len(r.operations)
        print(f"  {r.method}: {r.total_seconds:.2f}s ({successful_ops}/{total_ops} successful)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cluster_tools installation methods")
    parser.add_argument("--manual-only", action="store_true", help="Only run manual download benchmark")
    parser.add_argument("--nix-only", action="store_true", help="Only run Nix benchmark")
    parser.add_argument("--nix-shell", action="store_true", help="Also benchmark nix-shell (all at once)")
    parser.add_argument("--output", type=Path, help="Output JSON file for results")
    args = parser.parse_args()

    results = []

    # Create temp directory for manual downloads
    with tempfile.TemporaryDirectory() as tmpdir:
        tools_dir = Path(tmpdir) / "tools"
        tools_dir.mkdir()

        if not args.nix_only:
            results.append(benchmark_manual_download(tools_dir))

        if not args.manual_only:
            results.append(benchmark_nix_install_tools())

            if args.nix_shell:
                results.append(benchmark_nix_shell_all())

    print_comparison(results)

    if args.output:
        output_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "platform": platform.platform(),
            "arch": get_arch(),
            "results": [r.to_dict() for r in results],
        }
        args.output.write_text(json.dumps(output_data, indent=2))
        print(f"\nResults written to {args.output}")


if __name__ == "__main__":
    main()
