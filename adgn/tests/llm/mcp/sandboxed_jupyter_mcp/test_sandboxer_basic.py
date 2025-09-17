from pathlib import Path
import subprocess
import sys

import pytest
import yaml


@pytest.mark.macos
@pytest.mark.parametrize(
    ("name", "cmd", "passthrough", "expect_substring"),
    [
        (
            "yes_hello",
            ["/bin/sh", "-lc", "yes hello | head -n 5"],
            [],
            "hello",
        ),
        (
            "venv_python_hello",
            [sys.executable, "-c", "print('HELLO_VENV')"],
            ["PATH", "PYTHONPATH"],
            "HELLO_VENV",
        ),
    ],
)
def test_sandboxer_basic(
    tmp_path: Path,
    name: str,
    cmd: list[str],
    passthrough: list[str],
    expect_substring: str,
):
    run = tmp_path
    (run / "tmp").mkdir(parents=True, exist_ok=True)
    policy = run / f"policy_{name}.yaml"
    policy_dict = {
        "env": {
            "set": {
                "TMPDIR": (run / "tmp").as_posix(),
                "HOME": run.as_posix(),
                "PYTHONUNBUFFERED": "1",
            },
            "passthrough": passthrough,
        },
        "fs": {
            # Start permissive for convergence; we can narrow iteratively once green
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

    full_cmd = [
        sys.executable,
        "-m",
        "adgn.llm.sandboxer",
        "--policy",
        str(policy),
        "--trace",
        "--",
        *cmd,
    ]
    cp = subprocess.run(
        full_cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    # Emit for diagnostics on failure
    print("STDOUT:\n" + cp.stdout)
    print("STDERR:\n" + cp.stderr)
    assert cp.returncode == 0
    assert expect_substring in cp.stdout
