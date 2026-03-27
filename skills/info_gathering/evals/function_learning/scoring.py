"""Program evaluation for the function learning eval.

Evaluates the model's program against all inputs in a single Docker exec
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


def _hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two integers."""
    return (a ^ b).bit_count()


@dataclass
class ScoringResult:
    """Result of evaluating a program against all inputs."""

    hamming_loss: int
    errors: list[ProgramError]
    total_eval_s: float
    mean_per_input_s: float
    max_per_input_s: float


@dataclass
class _WrapperOutput:
    """Parsed output from eval_wrapper.py."""

    results: dict[str, str]
    errors: dict[str, str]
    timings: dict[str, float]


def _parse_wrapper_output(raw: str) -> _WrapperOutput:
    """Parse JSON output from the eval wrapper, raising on failure."""
    data = json.loads(raw.strip())
    return _WrapperOutput(
        results=data.get("results", {}), errors=data.get("errors", {}), timings=data.get("timings", {})
    )


def _score_input(inp: int, expected: int, wrapper: _WrapperOutput, m: int, errors: list[ProgramError]) -> int:
    """Score a single input, returning its hamming loss contribution."""
    inp_str = str(inp)
    if inp_str in wrapper.errors:
        if len(errors) < _MAX_REPORTED_ERRORS:
            errors.append(ProgramError(input=inp_str, error=wrapper.errors[inp_str]))
        return m
    if inp_str not in wrapper.results:
        if len(errors) < _MAX_REPORTED_ERRORS:
            errors.append(ProgramError(input=inp_str, error="Missing from results"))
        return m
    got = int(wrapper.results[inp_str])
    return _hamming_distance(expected, got)


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


def _max_loss(secret_fn: SecretFunction) -> int:
    return secret_fn.num_inputs * secret_fn.m


def _fail_result(error_msg: str, secret_fn: SecretFunction, total_eval_s: float) -> ScoringResult:
    return ScoringResult(
        hamming_loss=_max_loss(secret_fn),
        errors=[ProgramError(input="*", error=error_msg)],
        total_eval_s=total_eval_s,
        mean_per_input_s=0,
        max_per_input_s=0,
    )


async def evaluate_program(
    container: aiodocker.docker.DockerContainer, program: str, secret_fn: SecretFunction
) -> ScoringResult:
    """Evaluate program against all inputs in a single Docker exec call."""
    all_inputs = secret_fn.all_inputs()
    wrapper_source = get_required_path(_EVAL_WRAPPER_RLOCATION).read_text()
    config = json.dumps(
        {
            "program": program,
            "all_inputs": all_inputs,
            "timeout": _PER_INPUT_TIMEOUT_S,
            "max_output": secret_fn.max_output,
        }
    )
    loop = asyncio.get_running_loop()
    t0 = loop.time()

    raw = await _docker_exec(container, ["python3", "-c", wrapper_source, config], _EVAL_TIMEOUT_S)
    total_eval_s = loop.time() - t0

    try:
        wrapper = _parse_wrapper_output(raw)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse scoring output: %s (raw: %s)", e, raw[:300])
        return _fail_result(f"Parse error: {e}", secret_fn, total_eval_s)

    program_errors: list[ProgramError] = []
    hamming_loss = sum(
        _score_input(inp, secret_fn.evaluate(inp), wrapper, secret_fn.m, program_errors) for inp in all_inputs
    )

    elapsed_times = list(wrapper.timings.values())
    return ScoringResult(
        hamming_loss=hamming_loss,
        errors=program_errors,
        total_eval_s=total_eval_s,
        mean_per_input_s=sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0,
        max_per_input_s=max(elapsed_times) if elapsed_times else 0,
    )
