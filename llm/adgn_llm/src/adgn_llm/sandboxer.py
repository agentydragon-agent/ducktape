from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

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
    sysctl_read: bool | None = None
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
(allow file-read* (literal "/dev/null"))
(allow file-write* (literal "/dev/null"))
(allow file-read* (literal "/dev/urandom"))
(allow file-read* (literal "/dev/random"))
(allow file-read* (subpath "/dev/tty"))
(allow file-write* (subpath "/dev/tty"))

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

    # TODO(mpokorny): Prefer named seatbelt params again once param-related crashes are resolved.
    # Context: direct sandbox-exec with `(subpath (param "WP_*"))` produced errors like
    #   "invalid data type of path filter; expected pattern, got boolean" or exit 134 on this host.
    # For now, we inline literal paths to keep narrow policies working; restore `param` usage when fixed.
    lines.append(";; Writable dirs (WP_*): runtime/workspace; allow writes and exec of entrypoints within")
    for i, ap in enumerate(write_dirs):
        key = f"WP_{i}"
        defs[key] = ap
        lines.append(f'(allow file-write* (subpath "{ap}") )')
        # Exec is governed by file-map-executable and global process allowances

    # TODO(mpokorny): Restore named params `(param "RP_*")` for read paths once sandbox-exec param issues are clarified.
    # Temporary workaround: inline literal subpaths to avoid observed param parsing/abort behavior on this macOS version.
    lines.append(";; Readable dirs (RP_*): venv roots/bin, stdlib & site-packages")
    for i, ap in enumerate(read_dirs):
        key = f"RP_{i}"
        defs[key] = ap
        lines.append(f'(allow file-read* (subpath "{ap}") )')
        # Note: rely on global (allow file-map-executable); per-path filters are not supported uniformly

    # Parent directory metadata allowances to enable path traversal to allowed subpaths
    meta_parents: set[str] = set()
    def _add_parents(p: str):
        cur = Path(p)
        # Ascend to root, collecting literal parents
        while True:
            meta_parents.add(str(cur))
            if str(cur) == "/":
                break
            cur = cur.parent
    for ap in read_dirs:
        _add_parents(ap)
    for ap in write_dirs:
        _add_parents(ap)
    # Also include common system roots we already rely on
    for root in ("/opt", "/usr", "/private", "/System", "/Users"):
        meta_parents.add(root)
    lines.append(";; Parent directory metadata allowances to enable path traversal")
    for mp in sorted(meta_parents):
        lines.append(f'(allow file-read-metadata (literal "{mp}") )')


    # Platform seatbelt extras
    extra = policy.platform.seatbelt.extra_allow
    for p in (extra.file_read_extra or []):
        lines.append(f'(allow file-read* (subpath "{_abs(p)}") )')
    # Optional IPC/system allowances controlled by policy extras
    if extra.system_socket:
        lines.append('(allow system-socket)')
    if extra.sysctl_read:
        lines.append('(allow sysctl-read)')
    for name in (extra.mach_lookup or []):
        # Allow lookups of specific global Mach services
        lines.append(f'(allow mach-lookup (global-name "{name}"))')
    # dev.allow_tty_writes could toggle /dev/tty allow in future; keep default for now

    # Net rules (mode: none | loopback | all) — allowlist/proxy reserved for future
    mode = policy.net.mode
    if mode == "open":
        lines.append(';; Net mode=open: allow outbound (HTTP, etc.) and inbound (kernel ports)')
        lines.append('(allow network-outbound)')
        lines.append('(allow network-inbound)')
        lines.append('(allow network-bind)')
    elif mode == "loopback":
        # Allow ONLY local connections both directions (Jupyter↔kernel)
        lines.append(';; Net mode=loopback: only local connections in both directions (Jupyter↔kernel)')
        lines.append('(allow network-inbound (local ip))')
        lines.append('(allow network-outbound (local ip))')
        lines.append('(allow network-bind (local ip))')
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
    except Exception as e:
        print(f"sandboxer: invalid policy YAML: {e}", file=sys.stderr)
        return 2

    # Allow debug via env flag as well (SJ_DEBUG_DIAG=1)
    if not args.debug and os.environ.get("SJ_DEBUG_DIAG"):
        args.debug = True
    if args.trace or policy.platform.trace:
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
    # Write trace under a writable runtime dir (prefer TMPDIR from policy.env.set, then HOME), else tmpdir
    trace_path = None
    if policy.platform.trace or policy.platform.seatbelt.trace:
        env_set = (policy.env.set or {})
        tmp_hint = env_set.get("TMPDIR") or env_set.get("TMP") or env_set.get("TEMP")
        home_dir = env_set.get("HOME") or os.environ.get("HOME")
        if tmp_hint:
            base = Path(tmp_hint)
        elif home_dir:
            base = Path(home_dir)
        else:
            base = Path(tmpdir)
        base.mkdir(parents=True, exist_ok=True)
        tp = base / "seatbelt.trace.log"
        try:
            # Ensure file exists for diagnostics collection
            tp.touch(exist_ok=True)
        except Exception:
            pass
        trace_path = str(tp)
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
    # Optional policy echo for observability
    echo_dir = os.environ.get("SJ_POLICY_ECHO_DIR")
    if echo_dir:
        try:
            ed = Path(echo_dir)
            ed.mkdir(parents=True, exist_ok=True)
            (ed / "policy.sb").write_text(sb_text)
            (ed / "policy_defs.json").write_text(json.dumps(defs, indent=2))
            if args.debug:
                print(f"sandboxer: echoed policy and defs to {ed}", file=sys.stderr)
        except Exception as e:
            print(f"sandboxer: policy echo failed: {e}", file=sys.stderr)

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
