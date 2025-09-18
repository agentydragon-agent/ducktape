from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


@pytest.mark.macos
@pytest.mark.shell
def test_sandboxer_cli_allow_all_runs_echo(tmp_path: Path, require_sandbox_exec):
    run = tmp_path
    (run / "tmp").mkdir(parents=True, exist_ok=True)
    policy = run / "policy_allow_all.yaml"
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
        "net": {"mode": "open"},
        "platform": {
            "trace": False,
            "seatbelt": {"extra_allow": {"sysctl_read": True, "file_read_extra": []}},
        },
    }
    policy.write_text(yaml.safe_dump(policy_dict, sort_keys=False))

    cmd = [
        shutil.which("python3") or "python3",
        "-m",
        "adgn.llm.sandboxer",
        "--policy",
        str(policy),
        "--",
        "/bin/sh",
        "-c",
        "echo SANDBOXER_OK",
    ]
    cp = subprocess.run(cmd, text=True, capture_output=True, check=False)

    if cp.returncode != 0:
        print("STDOUT:\n" + cp.stdout)
        print("STDERR:\n" + cp.stderr)

    assert cp.returncode == 0
    assert "SANDBOXER_OK" in cp.stdout
