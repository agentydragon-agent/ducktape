# Early bootstrap to capture import/startup failures for ipykernel
from __future__ import annotations

import os
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path


def _runtime_dir() -> Path:
    # Prefer JUPYTER_RUNTIME_DIR (wrapper/policy sets this under run_root/runtime)
    rd = os.environ.get("JUPYTER_RUNTIME_DIR")
    if rd:
        try:
            p = Path(rd)
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    # Fallback to TMPDIR or home
    rd = (
        os.environ.get("TMPDIR")
        or os.environ.get("TMP")
        or os.environ.get("TEMP")
        or os.environ.get("HOME")
        or "."
    )
    p = Path(rd)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _log_path() -> Path:
    return _runtime_dir() / "kernel_boot.log"


def _log(msg: str) -> None:
    try:
        lp = _log_path()
        with lp.open("a", encoding="utf-8") as f:
            ts = datetime.now(UTC).isoformat(timespec="seconds") + "Z"
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # Never fail bootstrap due to logging
        pass


try:
    _log("bootstrap: starting ipykernel import")
    # ipykernel_launcher is how Jupyter starts kernels; mirror it but with logging around it
    from ipykernel import kernelapp as app  # type: ignore

    _log("bootstrap: imported ipykernel.kernelapp successfully")
    # Replicate behavior of ipykernel_launcher: run app.launch_new_instance()
    sys.argv = [sys.executable, "-m", "ipykernel_launcher", *sys.argv[1:]]
    app.launch_new_instance()
except SystemExit as e:
    # Normal exit path; still record it
    _log(f"bootstrap: SystemExit code={getattr(e, 'code', None)}")
    raise
except Exception:
    _log(
        "bootstrap: unhandled exception during kernel startup:\n"
        + traceback.format_exc(),
    )
    # Re-raise to preserve behavior; Jupyter will observe kernel crash and restart/log
    raise
