import sys
import subprocess
from pathlib import Path

import pytest


@pytest.mark.macos
def test_sandboxer_venv_python_prints_hello(tmp_path: Path):
    run = tmp_path
    (run / "tmp").mkdir(parents=True, exist_ok=True)
    import yaml
    policy = run / "policy.yaml"
    # Start permissive for convergence; we'll narrow iteratively once green
    policy_dict = {
        "env": {
            "set": {
                "TMPDIR": (run / "tmp").as_posix(),
                "HOME": run.as_posix(),
                "PYTHONUNBUFFERED": "1",
            },
            "passthrough": ["PATH", "PYTHONPATH"],
        },
        "fs": {
            "read_paths": ["/"],
            "write_paths": [run.as_posix()],
        },
        "net": {"mode": "none"},
        "platform": {
            "trace": True,
            "seatbelt": {"extra_allow": {"sysctl_read": True, "file_read_extra": []}},
        },
    }
    policy.write_text(yaml.safe_dump(policy_dict, sort_keys=False))
    cmd = [
        sys.executable,
        "-m",
        "jupyter_mcp_stdio_guard.sandboxer",
        "--policy",
        str(policy),
        "--trace",
        "--",
        sys.executable,
        "-c",
        "print('HELLO_VENV')",
    ]
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # Surface logs when it fails
    print("STDOUT:\n" + cp.stdout)
    print("STDERR:\n" + cp.stderr)
    assert cp.returncode == 0
    assert "HELLO_VENV" in cp.stdout
