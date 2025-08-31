import sys
import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.mark.macos
def test_sandboxer_yes_hello_world_narrow(tmp_path: Path):
    """Narrowed version of hello-world test: no read '/' — allow only minimal system paths.

    Runs a simple pipeline `yes hello | head -n 5` under a tight allowlist and prints
    diagnostic tails (seatbelt.trace + unified denies) when failing.
    """
    run = tmp_path
    (run / "tmp").mkdir(parents=True, exist_ok=True)

    policy = run / "policy_narrow.yaml"
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
            # Minimal system bins required by this test: sh/yes/head and loader essentials
            "read_paths": [
                run.as_posix(),
                (run / "tmp").as_posix(),
                "/bin",
                "/usr/bin",
                # loader + system framework essentials
                "/System",
                "/System/Library",
                "/usr/lib",
                "/usr/lib/dyld",
                "/private/var/db",
                "/private/var/db/dyld",
                "/var/db",
                "/System/Volumes/Preboot",
                "/System/Cryptexes",
                "/System/Volumes/Preboot/Cryptexes",
                # useful common dirs some tools read
                "/etc",
                "/private/etc",
                "/usr/share",
                "/usr/libexec",
                "/dev",
                "/usr/local",
                "/opt/homebrew",
            ],
            "write_paths": [run.as_posix()],
        },
        "net": {"mode": "none"},
        "platform": {
            "trace": True,
            "seatbelt": {"extra_allow": {"sysctl_read": True, "file_read_extra": [], "mach_lookup": ["com.apple.cfprefsd.agent"]}},
        },
    }
    policy.write_text(yaml.safe_dump(policy_dict, sort_keys=False))

    def _run_and_print(argv: list[str]) -> subprocess.CompletedProcess:
        cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("CMD:", " ".join(argv))
        print("STDOUT:\n" + cp.stdout)
        print("STDERR:\n" + cp.stderr)
        if cp.returncode != 0:
            # Print sandbox trace tail
            trace_path = run / "tmp" / "seatbelt.trace.log"
            try:
                if trace_path.exists():
                    lines = trace_path.read_text(errors="ignore").splitlines()
                    tail = "\n".join(lines[-200:])
                    print("=== seatbelt.trace.log (tail) ===\n" + tail)
                else:
                    print(f"=== seatbelt.trace.log missing: {trace_path} ===")
            except Exception as e:
                print(f"=== seatbelt.trace.log read error: {e} ===")
            # Print unified sandbox denies from system log (last 7 minutes)
            try:
                res = subprocess.run(
                    [
                        "/usr/bin/log",
                        "show",
                        "--style",
                        "syslog",
                        "--last",
                        "7m",
                        "--predicate",
                        '(subsystem == "com.apple.sandbox") && (eventMessage CONTAINS[c] "deny")',
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                u_lines = res.stdout.strip().splitlines()
                u_tail = "\n".join(u_lines[-200:])
                print("=== unified sandbox denies (tail, last 7m) ===\n" + u_tail)
            except Exception as e:
                print(f"=== unified sandbox denies read error: {e} ===")
        return cp

    # 1) Basic echo using /bin/echo (no shell)
    cp_echo = _run_and_print([
        sys.executable,
        "-m",
        "adgn_llm.sandboxer",
        "--policy",
        str(policy),
        "--trace",
        "--",
        "/bin/echo",
        "HELLO_ECHO",
    ])
    # 2) Shell pipeline yes|head
    cp_pipe = _run_and_print([
        sys.executable,
        "-m",
        "adgn_llm.sandboxer",
        "--policy",
        str(policy),
        "--trace",
        "--",
        "/bin/sh",
        "-lc",
        "yes hello | head -n 5",
    ])

    assert cp_echo.returncode == 0 and "HELLO_ECHO" in cp_echo.stdout
    assert cp_pipe.returncode == 0 and "hello" in cp_pipe.stdout
