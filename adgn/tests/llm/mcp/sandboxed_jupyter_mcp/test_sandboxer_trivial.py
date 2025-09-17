from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.mark.macos
def test_trivial_yes_hello_world(tmp_path: Path):
    run = tmp_path
    (run / "tmp").mkdir(parents=True, exist_ok=True)

    policy = run / "policy.yaml"
    policy_dict = {
        "env": {
            "set": {
                "TMPDIR": (run / "tmp").as_posix(),
                "HOME": run.as_posix(),
                "PYTHONUNBUFFERED": "1",
            },
            "passthrough": [],
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
        "adgn.llm.sandboxer",
        "--policy",
        str(policy),
        "--trace",
        "--",
        "/bin/sh",
        "-lc",
        "yes hello | head -n 5",
    ]
    # Capture outputs for diagnostics
    cp = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    print("STDOUT:\n" + cp.stdout)
    print("STDERR:\n" + cp.stderr)
    assert cp.returncode == 0
    assert "hello" in cp.stdout
