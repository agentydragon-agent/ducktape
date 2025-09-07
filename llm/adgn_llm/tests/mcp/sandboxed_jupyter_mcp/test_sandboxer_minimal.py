import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="seatbelt only on macOS",
)

# IMPORTANT: Do NOT "fix" this test by editing sandboxer.py defaults.
# Iterate by adjusting the YAML reference policy only.
# Sandboxer must remain a thin translator from YAML Policy -> SBPL.


def test_exec_true_minimal():
    policy_yaml = Path(__file__).resolve().parent / "policies/minimal_true.yaml"
    assert policy_yaml.exists(), f"Missing reference policy: {policy_yaml}"
    cmd = [
        sys.executable,
        "-m",
        "adgn_llm.sandboxer",
        "--policy",
        str(policy_yaml),
        "--trace",
        "--",
        "/usr/bin/true",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rc = proc.wait()
    if rc != 0:
        # Surface stderr to help diagnose missing allows; do NOT edit code defaults.
        err = (proc.stderr.read() or b"").decode("utf-8", "ignore")
        print("sandboxer stderr:\n" + err)
    assert rc == 0, "minimal /usr/bin/true under sandbox should succeed"
