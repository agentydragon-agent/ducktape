from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
import json


def _runtime_dir() -> Path:
    rd = os.environ.get("JUPYTER_RUNTIME_DIR") or os.environ.get("TMPDIR") or os.environ.get("HOME") or "."
    p = Path(rd)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _log_path(name: str = "kernel_boot.log") -> Path:
    return _runtime_dir() / name


def _log(msg: str) -> None:
    try:
        lp = _log_path()
        with lp.open("a", encoding="utf-8") as f:
            ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def main() -> int:
    try:
        _log("shim: starting kernel_shim")
        # Log basic environment for venv/API mismatch debugging
        info = {
            "sys.executable": sys.executable,
            "sys.version": sys.version,
            "argv": sys.argv,
            "env_subset": {k: os.environ.get(k) for k in [
                "PATH", "PYTHONPATH", "VIRTUAL_ENV", "JUPYTER_RUNTIME_DIR", "HOME", "TMPDIR"
            ]},
        }
        _log("shim: info=" + json.dumps(info, indent=2, default=str))
        # Also log first few entries of sys.path
        _log("shim: sys.path head=" + json.dumps(sys.path[:10]))
        # Try importing critical packages
        for mod in ("ipykernel", "jupyter_client", "zmq"):
            try:
                __import__(mod)
                _log(f"shim: import {mod} OK")
            except Exception as e:  # noqa: BLE001
                _log(f"shim: import {mod} FAILED: {e}\n" + traceback.format_exc())
        # Run ipykernel_launcher as if invoked with -m
        import runpy
        _log("shim: launching ipykernel_launcher")
        # Rewrite argv to mimic -m ipykernel_launcher execution
        sys.argv = [sys.executable, "-m", "ipykernel_launcher", *sys.argv[1:]]
        runpy.run_module("ipykernel_launcher", run_name="__main__")
        return 0
    except SystemExit as e:
        _log(f"shim: SystemExit code={getattr(e, 'code', None)}")
        raise
    except Exception:
        _log("shim: unhandled exception:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    raise SystemExit(main())
