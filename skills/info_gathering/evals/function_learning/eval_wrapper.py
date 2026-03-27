"""Evaluation wrapper script for function learning scoring.

Runs inside a Docker container. Reads a JSON config from argv[1] containing:
- program: The model's Python program source
- all_inputs: List of integer inputs to evaluate
- timeout: Per-input timeout in seconds
- max_output: Maximum valid output value

Outputs a JSON object to stdout with:
- results: {input: output} for successful evaluations (string keys/values)
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
    all_inputs: list[int] = config["all_inputs"]
    timeout: int = config["timeout"]
    max_output: int = config["max_output"]

    results: dict[str, str] = {}
    errors: dict[str, str] = {}
    timings: dict[str, float] = {}

    for inp in all_inputs:
        inp_str = str(inp)
        t0 = time.monotonic()
        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            sys.stdin = io.StringIO(inp_str + "\n")
            capture = io.StringIO()
            sys.stdout = capture
            exec(compile(program, "<program>", "exec"), {"__builtins__": __builtins__})
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            signal.alarm(0)
            raw_output = capture.getvalue().strip()
            # Validate: must be a non-negative integer in range.
            try:
                val = int(raw_output)
            except ValueError:
                errors[inp_str] = f"Not an integer: {raw_output!r}"
                timings[inp_str] = time.monotonic() - t0
                continue
            if val < 0 or val > max_output:
                errors[inp_str] = f"Out of range [0, {max_output}]: {val}"
                timings[inp_str] = time.monotonic() - t0
                continue
            results[inp_str] = raw_output
        except _TimeoutError:
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            errors[inp_str] = "timeout"
        except Exception as e:
            sys.stdout = sys.__stdout__
            sys.stdin = sys.__stdin__
            signal.alarm(0)
            errors[inp_str] = str(e)[:200]
        timings[inp_str] = time.monotonic() - t0

    print(json.dumps({"results": results, "errors": errors, "timings": timings}))


if __name__ == "__main__":
    main()
