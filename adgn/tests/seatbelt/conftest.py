from __future__ import annotations

import asyncio
import shutil

import pytest

from adgn.seatbelt.model import FileRule, PathFilter, ProcessRule, SBPLPolicy
from adgn.seatbelt.runner import apopen, run_sandboxed, run_sandboxed_async


@pytest.fixture(autouse=True)
def _seatbelt_require_sandbox_exec() -> None:
    if not shutil.which("sandbox-exec"):
        pytest.skip("sandbox-exec not found on PATH")


@pytest.fixture
def allow_all_policy() -> SBPLPolicy:
    return SBPLPolicy(
        default_behavior="allow",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
            FileRule(op="file-write*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
    )


@pytest.fixture
def restrictive_echo_policy() -> SBPLPolicy:
    # Default-deny + minimal read needed to exec echo on this host
    return SBPLPolicy(
        default_behavior="deny",
        process=ProcessRule(allow_process_star=True, allow_signal_self=True),
        files=[
            FileRule(op="file-map-executable", filters=[]),
            FileRule(op="file-read*", filters=[PathFilter(kind="subpath", value="/")]),
        ],
    )


@pytest.fixture
def policy_deny_users(allow_all_policy: SBPLPolicy) -> SBPLPolicy:
    p = allow_all_policy.model_copy(deep=True)
    p.files += [
        FileRule(
            op="file-read*",
            action="deny",
            filters=[PathFilter(kind="subpath", value="/Users")],
        ),
        FileRule(
            op="file-read-metadata",
            action="deny",
            filters=[PathFilter(kind="subpath", value="/Users")],
        ),
    ]
    return p


@pytest.fixture
async def cat_process(require_sandbox_exec, allow_all_policy: SBPLPolicy):
    p = await apopen(["/bin/sh", "-c", "cat"], allow_all_policy, trace=True)
    try:
        yield p
    finally:
        if p.stdin:
            p.stdin.close()
        try:
            await asyncio.wait_for(p.wait(), timeout=2)
        except Exception:
            p.kill()
            await p.wait()
        p.cleanup()


@pytest.fixture
def run_sync(require_sandbox_exec):
    def _run(policy: SBPLPolicy, argv: list[str], *, trace: bool = False):
        rr = run_sandboxed(policy, argv, trace=trace)
        if rr.exit_code != 0:
            print("\n=== seatbelt diagnostics (sync) ===")
            print(f"cmd: {' '.join(rr.cmd)}")
            print(
                "-- policy.sb (head) --\n" + "\n".join(rr.policy_text.splitlines()[:25])
            )
            if rr.unified_sandbox_denies_text:
                tail = "\n".join(
                    (rr.unified_sandbox_denies_text or "").splitlines()[-120:]
                )
                print("-- unified sandbox denies (tail) --\n" + tail)
            if rr.trace_text:
                print(
                    "-- seatbelt trace (tail) --\n"
                    + "\n".join((rr.trace_text or "").splitlines()[-120:])
                )
        return rr

    return _run


@pytest.fixture
def run_async(require_sandbox_exec):
    async def _run(policy: SBPLPolicy, argv: list[str], *, trace: bool = False):
        rr = await run_sandboxed_async(
            policy,
            argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            trace=trace,
        )
        if rr.exit_code != 0:
            print("\n=== seatbelt diagnostics (async) ===")
            print(f"cmd: {' '.join(rr.cmd)}")
            print(
                "-- policy.sb (head) --\n" + "\n".join(rr.policy_text.splitlines()[:25])
            )
            if rr.unified_sandbox_denies_text:
                tail = "\n".join(
                    (rr.unified_sandbox_denies_text or "").splitlines()[-120:]
                )
                print("-- unified sandbox denies (tail) --\n" + tail)
            if rr.trace_text:
                print(
                    "-- seatbelt trace (tail) --\n"
                    + "\n".join((rr.trace_text or "").splitlines()[-120:])
                )
        return rr

    return _run
