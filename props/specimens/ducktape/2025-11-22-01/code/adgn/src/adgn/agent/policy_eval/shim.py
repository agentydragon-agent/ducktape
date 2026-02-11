"""
Policy evaluator shim module.

This module runs inside the policy evaluation container. It reads two
environment variables provided by the host:

- POLICY_SRC: the policy program source code (Python)
- POLICY_INPUT: the JSON request payload (string)

It sets sys.stdin to a StringIO over POLICY_INPUT so that policy programs that
read from stdin see the request. Then it exec()s POLICY_SRC. The policy program
is responsible for printing a single JSON line (PolicyResponse) to stdout.

Notes:
- Keep this tiny and dependency-free; only stdlib is used.
- Container image must have the adgn package installed so `python -m
  adgn.agent.policy_eval.shim` resolves.
"""

from __future__ import annotations

import io
import os
import sys


def main() -> None:
    src = os.environ.get("POLICY_SRC", "")
    inp = os.environ.get("POLICY_INPUT", "")
    # Provide stdin to policy program
    sys.stdin = io.StringIO(inp)
    # Execute policy source with __name__ set to "__main__" so that
    # policies that gate their entrypoint under if __name__ == "__main__": run(...)
    # will execute as expected.
    exec(compile(src, "<policy>", "exec"), {"__name__": "__main__"})


if __name__ == "__main__":
    main()
