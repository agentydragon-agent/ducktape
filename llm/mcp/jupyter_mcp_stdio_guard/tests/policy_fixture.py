from pathlib import Path
import os
import yaml


def write_policy(ws: Path, run_root: Path) -> None:
    for sub in ("runtime", "data", "config", "mpl", "pycache", "tmp"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    # New explicit-only policy; default to broad read to keep tests simple
    cfg = {
        "allow_read_all": True,
        "allow_write_all": False,
        "read_paths": [],
        "write_paths": [str(ws), str(run_root)],
        # TODO(net): implement later
        "env": {
            # Put session control venv first (set by bootstrap), then system PATH
            "PATH": (os.environ.get("SJ_TEST_CONTROL_BIN", "") + (":" if os.environ.get("SJ_TEST_CONTROL_BIN") else "")) + os.environ.get("PATH", ""),
            "JUPYTER_RUNTIME_DIR": str(run_root / "runtime"),
            "JUPYTER_DATA_DIR": str(run_root / "data"),
            "JUPYTER_CONFIG_DIR": str(run_root / "config"),
            "JUPYTER_PATH": str(run_root / "data"),
            "MPLCONFIGDIR": str(run_root / "mpl"),
            "PYTHONPYCACHEPREFIX": str(run_root / "pycache"),
            "TMPDIR": str(run_root / "tmp"),
            "TMP": str(run_root / "tmp"),
            "TEMP": str(run_root / "tmp"),
            "PYTHONUNBUFFERED": "1",
        },
        # With a pinned control venv path on PATH, no HOME passthrough is needed
        "env_passthrough": [],
    }
    (ws / ".sandbox_jupyter.yaml").write_text(
        yaml.safe_dump(cfg, sort_keys=False)
    )
