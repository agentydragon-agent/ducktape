"""Evaluation wrapper script for function learning scoring.

Runs inside a Docker container. Reads a JSON config from argv[1] containing:
- program: The model's Python program source
- all_inputs: List of binary input strings to evaluate
- timeout: Per-input timeout in seconds

Outputs a JSON object to stdout with:
- results: {input: output} for successful evaluations
- errors: {input: error_message} for failures
- timings: {input: seconds} for all inputs
"""

import io
import json
import signal
import sys
import time


class _TimeoutError(Exception):
    pass


def _handler(signum: int, frame: object) -> None:
    raise _TimeoutError


def main() -> None:
    config = json.loads(sys.argv[1])
    program: str = config["program"]
    all_inputs: list[str] = config["all_inputs"]
    timeout: int = config["timeout"]

    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    timings: dict[str, float] = {}

    for inp in all_inputs:
        t0 = time.monotonic()
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            sys.stdin = io.StringIO(inp + "\n")
            capture = io.StringIO()
            sys.stdout = capture
            exec(compile(program, "<program>", "exec"), {"__builtins__": __builtins__})
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            signal.alarm(0)
            results[inp] = capture.getvalue().strip()
        except _TimeoutError:
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            errors[inp] = "timeout"
        except Exception as e:
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            signal.alarm(0)
            errors[inp] = str(e)[:200]
        timings[inp] = time.monotonic() - t0

    print(json.dumps({"results": results, "errors": errors, "timings": timings}))


if __name__ == "__main__":
    main()
