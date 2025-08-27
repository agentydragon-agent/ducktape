#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# -----------------------------
# Pydantic models for policy
# -----------------------------

class EnvConfig(BaseModel):
    set: dict[str, str] = Field(default_factory=dict)
    passthrough: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class FSConfig(BaseModel):
    read_paths: list[str] = Field(default_factory=list)
    write_paths: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class SeatbeltDevConfig(BaseModel):
    allow_tty_writes: bool | None = None

    class Config:
        extra = "forbid"


class SeatbeltExtraAllow(BaseModel):
    mach_lookup: list[str] = Field(default_factory=list)
    system_socket: bool | None = None
    dev: SeatbeltDevConfig = Field(default_factory=SeatbeltDevConfig)
    file_read_extra: list[str] = Field(default_factory=list)

    class Config:
        extra = "forbid"


class SeatbeltPlatform(BaseModel):
    trace: bool = False
    extra_allow: SeatbeltExtraAllow = Field(default_factory=SeatbeltExtraAllow)

    class Config:
        extra = "forbid"


class PlatformConfig(BaseModel):
    seatbelt: SeatbeltPlatform = Field(default_factory=SeatbeltPlatform)

    class Config:
        extra = "forbid"


class NetProxyConfig(BaseModel):
    listen: str | None = None  # e.g., 127.0.0.1:0
    upstream: str | None = None  # e.g., host:port

    class Config:
        extra = "forbid"


class NetConfig(BaseModel):
    mode: Literal["none", "loopback", "open"] = "loopback"
    allow_domains: list[str] = Field(default_factory=list)
    proxy: NetProxyConfig | None = None

    class Config:
        extra = "forbid"


class Policy(BaseModel):
    env: EnvConfig = Field(default_factory=EnvConfig)
    fs: FSConfig = Field(default_factory=FSConfig)
    net: NetConfig = Field(default_factory=NetConfig)
    platform: PlatformConfig = Field(default_factory=PlatformConfig)

    class Config:
        extra = "forbid"


# -----------------------------
# Seatbelt base and rendering
# -----------------------------

SEATBELT_BASE = """
(version 1)
(deny default)

;; Process primitives
(allow process*)
(allow signal (target self))

;; File/device basics
(allow file* (literal "/dev/null"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file* (subpath "/dev/tty"))

;; IPC and system lookups used by Python/stdlib
(allow ipc-posix-shm)
(allow ipc-posix-sem)
(allow ipc-sysv-shm)
(allow mach-lookup)
(allow system-socket)
(allow sysctl-read)
""".strip()


def _abs(p: str) -> str:
    return str(Path(p).resolve())


def _compose_seatbelt(policy: Policy, trace_path: str | None) -> tuple[str, dict[str, str]]:
    lines: list[str] = [SEATBELT_BASE]
    defs: dict[str, str] = {}

    # Optional trace
    if trace_path or policy.platform.seatbelt.trace:
        lines.append(f'(trace "{trace_path or "<trace>"}")')

    # FS rules
    fs = policy.fs
    write_paths = [_abs(p) for p in (fs.write_paths or [])]
    read_paths = [_abs(p) for p in (fs.read_paths or [])]

    # Allow writes under configured write_paths (via named params)
    for i, p in enumerate(write_paths):
        key = f"WP_{i}"
        defs[key] = p
        lines.append(f'(allow file* (subpath (param "{key}")) )')
        # Exec allowed under writable paths
        lines.append(f'(allow process-exec (subpath (param "{key}")) )')

    # Allow reads under configured read_paths (via named params)
    for i, p in enumerate(read_paths):
        key = f"RP_{i}"
        defs[key] = p
        if Path(p).is_dir():
            lines.append(f'(allow file-read* (subpath (param "{key}")) )')
            # Exec allowed wherever readable
            lines.append(f'(allow process-exec (subpath (param "{key}")) )')
        else:
            # For explicit file paths, allow literal match
            lines.append(f'(allow file-read* (literal (param "{key}")) )')
            lines.append(f'(allow process-exec (literal (param "{key}")) )')

    # Platform seatbelt extras
    extra = policy.platform.seatbelt.extra_allow
    for p in (extra.file_read_extra or []):
        lines.append(f'(allow file-read* (subpath "{_abs(p)}") )')
    # dev.allow_tty_writes could toggle /dev/tty allow in future; keep default for now

    # Net rules (mode: none | loopback | all) — allowlist/proxy reserved for future
    mode = policy.net.mode
    if mode == "open":
        lines.append('(allow network-outbound)')
        lines.append('(allow network-inbound)')
    elif mode == "loopback":
        # Allow kernels to receive local connections (Jupyter connects to kernel)
        lines.append('(allow network-inbound (local ip))')
        # No outbound allow → default deny
    elif mode == "none":
        # No network rules → default deny inbound/outbound
        pass
    else:
        # allowlist/proxy reserved for future; default to loopback behavior minimally
        lines.append('(allow network-inbound (local ip))')

    return "\n".join(lines) + "\n", defs


# -----------------------------
# CLI entry
# -----------------------------

def main() -> int:
    ap = argparse.ArgumentParser(prog="sandboxer", description="Run a command under a YAML-defined sandbox (macOS seatbelt MVP)")
    ap.add_argument("--policy", required=True, help="Path to policy.yaml (explicit-only schema)")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute (prefix with -- to separate)")
    args = ap.parse_args()

    if not args.cmd:
        print("sandboxer: missing command after --", file=sys.stderr)
        return 2
    # Drop a leading "--" separator if present
    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("sandboxer: empty command", file=sys.stderr)
        return 2

    raw = yaml.safe_load(Path(args.policy).read_text())
    try:
        policy = Policy(**raw)
    except Exception as e:  # noqa: BLE001
        print(f"sandboxer: invalid policy YAML: {e}", file=sys.stderr)
        return 2

    # Platform gate: only macOS seatbelt for MVP
    if sys.platform != "darwin":
        print("sandboxer: unsupported platform for MVP (only macOS supported)", file=sys.stderr)
        return 3

    # Env construction for child
    child_env: dict[str, str] = {}
    for name in policy.env.passthrough:
        if name in os.environ:
            child_env[name] = os.environ[name]
    # Explicit set wins
    for k, v in (policy.env.set or {}).items():
        child_env[k] = str(v)

    # Compose seatbelt policy file
    tmpdir = tempfile.mkdtemp(prefix="sandboxer-")
    trace_path = str(Path(tmpdir) / "trace.sb") if policy.platform.seatbelt.trace else None
    sb_path = Path(tmpdir) / "policy.sb"
    sb_text, defs = _compose_seatbelt(policy, trace_path)
    sb_path.write_text(sb_text)

    # Resolve sandbox-exec
    sx = shutil.which("sandbox-exec")
    if not sx:
        print("sandboxer: sandbox-exec not found (macOS only)", file=sys.stderr)
        return 4

    # Execute under sandbox
    try:
        sx_args = [sx]
        for k, v in defs.items():
            sx_args += ["-D", f"{k}={v}"]
        sx_args += ["-f", str(sb_path), *cmd]
        proc = subprocess.Popen(sx_args, env=child_env)
        return proc.wait()
    finally:
        # Keep tmpdir for trace inspection on failure; otherwise could be cleaned
        pass


if __name__ == "__main__":
    raise SystemExit(main())
