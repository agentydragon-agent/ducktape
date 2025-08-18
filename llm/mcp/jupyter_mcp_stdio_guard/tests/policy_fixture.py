from pathlib import Path
import os
import yaml


def write_policy(ws: Path, run_root: Path) -> None:
    for sub in ("runtime", "data", "config", "mpl", "pycache", "tmp"):
        (run_root / sub).mkdir(parents=True, exist_ok=True)
    cfg = {
        "workspace": str(ws),
        "run_root": str(run_root),
        "fs_write": [str(ws), str(run_root)],
        "fs_read": [],
        "net": "loopback",
        "env": {
            # Explicit env: include PATH so child can resolve binaries like jupyter and jupyter-mcp-server
            "PATH": os.environ.get("PATH", ""),
            "JUPYTER_RUNTIME_DIR": str(run_root / "runtime"),
            "JUPYTER_DATA_DIR": str(run_root / "data"),
            "JUPYTER_CONFIG_DIR": str(run_root / "config"),
            "JUPYTER_PATH": str(run_root / "data"),
            "MPLCONFIGDIR": str(run_root / "mpl"),
            "PYTHONPYCACHEPREFIX": str(run_root / "pycache"),
            "TMPDIR": str(run_root / "tmp"),
            "TMP": str(run_root / "tmp"),
            "TEMP": str(run_root / "tmp"),
            "HOME": str(run_root),
            "PYTHONUNBUFFERED": "1",
        },
    }
    (ws / ".sandbox_jupyter.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
