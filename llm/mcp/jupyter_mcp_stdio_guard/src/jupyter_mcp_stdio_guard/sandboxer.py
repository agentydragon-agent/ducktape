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
    # Platform-neutral tracing toggle; backends may map to their own tracing
    trace: bool = False
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

;; Process primitives (subprocess, fork/exec, signals to self)
(allow process*)
(allow signal (target self))

;; File/device basics
;; - /dev/null for stdio redirection
;; - /dev/urandom, /dev/random for Python's os.urandom and secrets
;; - /dev/tty for TTY-backed stdio when present
(allow file* (literal "/dev/null"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file* (subpath "/dev/tty"))

;; Exec mapping and core system reads needed by dyld/loader
;; - file-map-executable: allow mapping executable pages for dynamic loader
;; - /System, /usr/lib: system frameworks and libraries (libSystem, CF, etc.)
;; - /private/var/db/dyld: dyld shared cache and accelerator entries
(allow file-map-executable)
(allow file-read* (subpath "/System"))
(allow file-read* (subpath "/usr/lib"))
(allow file-read* (subpath "/private/var/db/dyld"))
(allow file-read* (subpath "/System/Volumes/Preboot"))
(allow file-read* (subpath "/System/Cryptexes"))
(allow file-read* (subpath "/System/Volumes/Preboot/Cryptexes"))

;; IPC and system lookups used by Python/stdlib
;; - POSIX/System V IPC used by multiprocessing/shared memory
;; - mach-lookup and system-socket for resolver, launch services lookups
;; - sysctl-read for platform/system info queries
(allow ipc-posix-shm)
(allow ipc-posix-sem)
(allow ipc-sysv-shm)
(allow mach-lookup)
(allow system-socket)
(allow sysctl-read)
""".strip()


def _abs(p: str) -> str:
    # Preserve symlinks to allow exec via symlink paths; avoid resolve()
    return str(Path(p).expanduser().absolute())


def _compose_seatbelt(policy: Policy, trace_path: str | None) -> tuple[str, dict[str, str]]:
    lines: list[str] = [SEATBELT_BASE]
    defs: dict[str, str] = {}

    # Optional trace
    if trace_path or policy.platform.seatbelt.trace:
        lines.append(f'(trace "{trace_path or "<trace>"}")')

    # FS rules
    fs = policy.fs
    raw_write = [Path(_abs(p)) for p in (fs.write_paths or [])]
    raw_read = [Path(_abs(p)) for p in (fs.read_paths or [])]

    # Normalize to directory subpaths to cover symlink/real and intermediates
    write_dirs: list[str] = []
    for p in raw_write:
        d = p if p.is_dir() else p.parent
        ap = str(d)
        if ap not in write_dirs:
            write_dirs.append(ap)
    read_dirs: list[str] = []
    for p in raw_read:
        # allow both symlink dir and resolved real dir
        dirs = []
        d = p if p.is_dir() else p.parent
        dirs.append(d)
        try:
            rp = p.resolve(strict=False)
            rd = rp if rp.is_dir() else rp.parent
            dirs.append(rd)
        except Exception:
            pass
        for dd in dirs:
            ap = str(dd)
            if ap not in read_dirs:
                read_dirs.append(ap)

    # Allow writes under configured write dirs (via named params)
    lines.append(";; Writable dirs (WP_*): runtime/workspace; allow writes and exec of entrypoints within")
    for i, ap in enumerate(write_dirs):
        key = f"WP_{i}"
        defs[key] = ap
        lines.append(f'(allow file* (subpath (param "{key}")) )')
        # Exec is governed by file-map-executable and global process allowances
        # (process-exec filter omitted for compatibility)

    # Allow reads under configured read dirs (via named params)
    lines.append(";; Readable dirs (RP_*): venv roots/bin, stdlib & site-packages; allow exec for interpreters/entrypoints")
    for i, ap in enumerate(read_dirs):
        key = f"RP_{i}"
        defs[key] = ap
        lines.append(f'(allow file-read* (subpath (param "{key}")) )')
        # Allow mapping executable pages from these dirs for dynamic loader
        lines.append(f'(allow file-map-executable (subpath (param "{key}")) )')
        # Note: process-exec filter omitted (use file-map-executable + allow process*)
    # Platform seatbelt extras
    extra = policy.platform.seatbelt.extra_allow
    for p in (extra.file_read_extra or []):
        lines.append(f'(allow file-read* (subpath "{_abs(p)}") )')
    # dev.allow_tty_writes could toggle /dev/tty allow in future; keep default for now

    # Net rules (mode: none | loopback | all) — allowlist/proxy reserved for future
    mode = policy.net.mode
    if mode == "open":
        lines.append(';; Net mode=open: allow outbound (HTTP, etc.) and inbound (kernel ports)')
        lines.append('(allow network-outbound)')
        lines.append('(allow network-inbound)')
    elif mode == "loopback":
        # Allow kernels to receive local connections (Jupyter connects to kernel)
        lines.append(';; Net mode=loopback: only inbound local connections (Jupyter→kernel), no outbound')
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
    ap.add_argument("--trace", action="store_true", help="Enable seatbelt trace logging")
    ap.add_argument("--debug", action="store_true", help="Verbose diagnostics (policy path, -D params)")
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

    if args.trace:
        # Platform-neutral trace flag; individual backends may not support it
        policy.platform.trace = True

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

    # Ensure expected runtime dirs exist (TMPDIR/TMP/TEMP, MPLCONFIGDIR, PYTHONPYCACHEPREFIX)
    for key in ("TMPDIR", "TMP", "TEMP", "MPLCONFIGDIR", "PYTHONPYCACHEPREFIX"):
        p = child_env.get(key)
        if p:
            try:
                Path(p).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    # Compose seatbelt policy file
    tmpdir = tempfile.mkdtemp(prefix="sandboxer-")
    # Write trace under a writable runtime dir (HOME) if available, else tmpdir
    trace_path = None
    if policy.platform.trace or policy.platform.seatbelt.trace:
        home_dir = (policy.env.set or {}).get("HOME") or os.environ.get("HOME")
        base = Path(home_dir) if home_dir else Path(tmpdir)
        trace_path = str(base / "seatbelt.trace.log")
    sb_path = Path(tmpdir) / "policy.sb"
    sb_text, defs = _compose_seatbelt(policy, trace_path)
    sb_path.write_text(sb_text)
    if args.debug:
        print(f"sandboxer: policy at {sb_path}", file=sys.stderr)
    if trace_path:
        print(f"sandboxer: trace to {trace_path}", file=sys.stderr)
    if args.debug and defs:
        for k, v in defs.items():
            print(f"sandboxer: -D {k}={v}", file=sys.stderr)

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
        if args.debug:
            import shlex as _sh
            print("sandboxer: exec:", " ".join(_sh.quote(x) for x in sx_args), file=sys.stderr)
        proc = subprocess.Popen(sx_args, env=child_env)
        return proc.wait()
    finally:
        # Keep tmpdir for trace inspection on failure; otherwise could be cleaned
        pass


if __name__ == "__main__":
    raise SystemExit(main())
