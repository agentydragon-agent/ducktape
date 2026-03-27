"""Program evaluation for the function learning eval.

Evaluates the model's program against all 2^N inputs in a single Docker exec
call using eval_wrapper.py. Uses aiodocker directly (no MCP layer) for clean
stdout access.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

import aiodocker

from skills.info_gathering.evals.function_learning.functions import SecretFunction
from skills.info_gathering.evals.function_learning.result_types import ProgramError
from util.bazel.runfiles import get_required_path

logger = logging.getLogger(__name__)

_MAX_REPORTED_ERRORS = 5
_EVAL_TIMEOUT_S = 30
_PER_INPUT_TIMEOUT_S = 1

_EVAL_WRAPPER_RLOCATION = "_main/skills/info_gathering/evals/function_learning/eval_wrapper.py"


def _hamming_distance(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b, strict=True))


@dataclass
class ScoringResult:
    """Result of evaluating a program against all inputs."""

    hamming_loss: int
    errors: list[ProgramError]
    total_eval_s: float
    mean_per_input_s: float
    max_per_input_s: float


async def _docker_exec(container: aiodocker.docker.DockerContainer, cmd: list[str], timeout_s: int) -> str:
    """Run a command in a container and return stdout."""
    exec_obj = await container.exec(cmd, stdout=True, stderr=True, stdin=False, tty=False)
    stream = exec_obj.start()
    chunks: list[bytes] = []
    try:
        async with asyncio.timeout(timeout_s):
            while msg := await stream.read_out():
                chunks.append(msg.data)
    except TimeoutError:
        chunks.append(b"\n[TIMEOUT]\n")
    return b"".join(chunks).decode("utf-8", errors="replace")


async def evaluate_program(
    container: aiodocker.docker.DockerContainer, program: str, secret_fn: SecretFunction
) -> ScoringResult:
    """Evaluate program against all inputs in a single Docker exec call."""
    all_inputs = secret_fn.all_inputs()
    wrapper_source = get_required_path(_EVAL_WRAPPER_RLOCATION).read_text()
    config = json.dumps({"program": program, "all_inputs": all_inputs, "timeout": _PER_INPUT_TIMEOUT_S})
    loop = asyncio.get_running_loop()
    t0 = loop.time()

    raw = await _docker_exec(container, ["python3", "-c", wrapper_source, config], _EVAL_TIMEOUT_S)
    total_eval_s = loop.time() - t0

    # Parse JSON output — it's raw stdout, no MCP wrapping.
    data: dict = {}
    try:
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("{") and "results" in stripped:
                data = json.loads(stripped)
                break
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse scoring output: %s (raw: %s)", e, raw[:300])
        max_loss = len(all_inputs) * secret_fn.m
        return ScoringResult(
            hamming_loss=max_loss,
            errors=[ProgramError(input="*", error=f"JSON parse error: {e}")],
            total_eval_s=total_eval_s,
            mean_per_input_s=0,
            max_per_input_s=0,
        )

    if not data:
        logger.warning("No JSON found in scoring output: %s", raw[:500])
        max_loss = len(all_inputs) * secret_fn.m
        return ScoringResult(
            hamming_loss=max_loss,
            errors=[ProgramError(input="*", error=f"No output from wrapper: {raw[:200]}")],
            total_eval_s=total_eval_s,
            mean_per_input_s=0,
            max_per_input_s=0,
        )

    results: dict[str, str] = data.get("results", {})
    raw_errors: dict[str, str] = data.get("errors", {})
    timings: dict[str, float] = data.get("timings", {})

    hamming_loss = 0
    program_errors: list[ProgramError] = []
    elapsed_times = list(timings.values()) if timings else []

    for inp in all_inputs:
        expected = secret_fn.evaluate(inp)
        if inp in raw_errors:
            hamming_loss += secret_fn.m
            if len(program_errors) < _MAX_REPORTED_ERRORS:
                program_errors.append(ProgramError(input=inp, error=raw_errors[inp]))
        elif inp in results:
            got = results[inp]
            if len(got) != secret_fn.m or not all(c in "01" for c in got):
                hamming_loss += secret_fn.m
                if len(program_errors) < _MAX_REPORTED_ERRORS:
                    if len(got) != secret_fn.m:
                        msg = f"Wrong length: expected {secret_fn.m} chars, got {len(got)} ({got[:50]!r})"
                    else:
                        msg = f"Non-binary characters in output: {got!r}"
                    program_errors.append(ProgramError(input=inp, error=msg))
            else:
                hamming_loss += _hamming_distance(expected, got)
        else:
            hamming_loss += secret_fn.m
            if len(program_errors) < _MAX_REPORTED_ERRORS:
                program_errors.append(ProgramError(input=inp, error="Missing from results"))

    return ScoringResult(
        hamming_loss=hamming_loss,
        errors=program_errors,
        total_eval_s=total_eval_s,
        mean_per_input_s=sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0,
        max_per_input_s=max(elapsed_times) if elapsed_times else 0,
    )
