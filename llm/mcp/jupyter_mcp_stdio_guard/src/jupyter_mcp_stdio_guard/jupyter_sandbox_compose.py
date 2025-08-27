#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
import sys
from typing import Iterable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _kernel_site_packages(kernel_python: str) -> str:
    # Derive site-packages/purelib for the provided kernel python
    code = (
        "import sysconfig, json; print(json.dumps(sysconfig.get_paths()))"
    )
    out = subprocess.check_output([kernel_python, "-c", code], text=True)
    paths = json.loads(out)
    # Prefer purelib, fall back to platlib
    return paths.get("purelib") or paths.get("platlib")


def _default_policy(control_dir: Path, site_packages: str) -> CommentedMap:
    yaml = YAML()
    data = CommentedMap()
    data.yaml_set_start_comment(
        "Explicit-only sandbox policy (precomposed)\n"
        "Adjust read_paths/write_paths to include your project workspace as needed."
    )

    env_map = CommentedMap()
    env_set = CommentedMap()
    env_set["HOME"] = control_dir.as_posix()
    env_set["PYTHONPYCACHEPREFIX"] = (control_dir / "pycache").as_posix()
    env_set["MPLCONFIGDIR"] = (control_dir / "mpl").as_posix()
    env_map["set"] = env_set
    env_map["passthrough"] = CommentedSeq()
    data["env"] = env_map

    fs_map = CommentedMap()
    fs_map["allow_read_all"] = False
    fs_map["allow_write_all"] = False
    fs_map["read_paths"] = CommentedSeq([site_packages, control_dir.as_posix()])
    fs_map["write_paths"] = CommentedSeq([control_dir.as_posix()])
    data["fs"] = fs_map

    net_map = CommentedMap()
    net_map["mode"] = "loopback"
    net_map.yaml_add_eol_comment("none|loopback|all|allowlist|proxy", "mode")
    data["net"] = net_map

    platform_map = CommentedMap()
    seatbelt_map = CommentedMap()
    seatbelt_map["trace"] = False
    extra_allow = CommentedMap()
    extra_allow["file_read_extra"] = CommentedSeq([
        "/System/Library/Fonts",
        "/Library/Fonts",
    ])
    seatbelt_map["extra_allow"] = extra_allow
    platform_map["seatbelt"] = seatbelt_map
    data["platform"] = platform_map
    return data


def _deep_merge(dst: CommentedMap, src: dict | CommentedMap) -> CommentedMap:
    for k, v in (src.items() if isinstance(src, dict) else src.items()):
        if k in dst and isinstance(dst[k], (dict, CommentedMap)) and isinstance(v, (dict, CommentedMap)):
            dst[k] = _deep_merge(dst[k], v)  # type: ignore[index]
        elif k in dst and isinstance(dst[k], (list, CommentedSeq)) and isinstance(v, (list, CommentedSeq)):
            # Append unique items while preserving order
            seen = set(dst[k])  # type: ignore[arg-type]
            for item in v:  # type: ignore[assignment]
                if item not in seen:
                    dst[k].append(item)  # type: ignore[index]
                    seen.add(item)
        else:
            dst[k] = v  # type: ignore[index]
    return dst


def compose(
    *,
    control_dir: Path,
    kernel_python: str,
    profiles: list[str] | dict[str, dict],
    sandboxer_python: str | None = None,
) -> None:
    control_dir = control_dir.resolve()
    config_dir = control_dir / "jupyter" / "config"
    kernels_dir = control_dir / "kernels"
    policies_dir = control_dir / "policies"

    for d in (config_dir, kernels_dir, policies_dir):
        _ensure_dir(d)

    # Write Jupyter server config (locked kernels, localhost only)
    (config_dir / "jupyter_server_config.py").write_text(
        "\n".join(
            [
                "c = get_config()",
                "c.KernelSpecManager.ensure_native_kernel = False",
                "c.ServerApp.open_browser = False",
                "c.ServerApp.ip = '127.0.0.1'",
                "c.ServerApp.disable_check_xsrf = True",
                "# Note: Jupyter may log once that websocket_ping_timeout>interval and then clamp.",
                "# Keeping both at 30000 here; the warning is benign and behavior is correct post-clamp.",
                "c.ServerApp.websocket_ping_interval = 30000",
                "c.ServerApp.websocket_ping_timeout = 30000",
                # Mirror on NotebookApp as some stacks still set these there (Jupyter will forward).
            ]
        )
        + "\n"
    )

    site_packages = _kernel_site_packages(kernel_python)

    # Compose per-profile policy.yaml and kernelspecs
    # Accept either a list of profile names (defaults) or a dict of name->policy overrides
    if isinstance(profiles, dict):
        profile_iter = list(profiles.items())
    else:
        profile_iter = [(p, {}) for p in profiles]

    for profile, overrides in profile_iter:
        prof_dir = policies_dir / profile
        _ensure_dir(prof_dir)
        policy_path = prof_dir / "policy.yaml"

        # Build policy YAML using ruamel.yaml (preserves ordering and allows comments)
        yaml = YAML()
        yaml.indent(mapping=2, sequence=4, offset=2)

        base = _default_policy(control_dir, site_packages)
        # Apply overrides (structured representation) if provided
        if overrides:
            base = _deep_merge(base, overrides)

        with policy_path.open("w") as f:
            yaml.dump(base, f)

        # Kernelspec
        kdir = kernels_dir / f"python3-{profile}"
        _ensure_dir(kdir)
        # Use explicit sandboxer_python if provided; otherwise default to current interpreter
        sb_py = sandboxer_python or sys.executable
        env_block = {}
        if os.environ.get("PYTHONPATH"):
            env_block["PYTHONPATH"] = os.environ["PYTHONPATH"]
        kernel_json = {
            "argv": [
                sb_py,
                "-m",
                "jupyter_mcp_stdio_guard.sandboxer",
                "--policy",
                policy_path.as_posix(),
                "--",
                kernel_python,
                "-m",
                "ipykernel_launcher",
                "-f",
                "{connection_file}",
            ],
            "display_name": f"Python 3 ({profile})",
            "language": "python",
            **({"env": env_block} if env_block else {}),
        }
        (kdir / "kernel.json").write_text(json.dumps(kernel_json))


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="jupyter-sandbox-compose",
        description="One-time composer to build a control bundle (config/kernels/policies)",
    )
    ap.add_argument("--control-dir", required=True, help="Output directory for control bundle")
    ap.add_argument("--kernel-python", required=True, help="Path to kernel python interpreter")
    ap.add_argument(
        "--profiles",
        default="low,high",
        help="Comma-separated list of profile names (e.g., low,high)",
    )

    args = ap.parse_args()
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    if not profiles:
        print("No profiles specified", file=sys.stderr)  # type: ignore[name-defined]
        return 2

    compose(
        control_dir=Path(args.control_dir),
        kernel_python=args.kernel_python,
        profiles=profiles,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
