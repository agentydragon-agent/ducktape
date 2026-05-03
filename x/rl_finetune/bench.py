#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Throughput benchmark for GRPO Wordle training.

Each probe is a subprocess of `wordle_train.py --metrics-out=<json>`. We read
the JSON back. Server-mode probes share one `trl vllm-serve`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).parent
LOGDIR = Path("/tmp/wordle_bench")
VLLM_PORT = 8000
MAX_STEPS = 10
N_PROMPTS = 640

# (name, mode, extra wordle_train.py flags, num_generations, extra vllm-serve flags).
# Probes from a previous run already have their *.metrics.json on disk; the
# re-runner reads ALL probes' JSONs at the end, so commented-out ones still
# appear in the table. Uncomment to re-measure.
PROBES: list[tuple[str, str, list[str], int, list[str]]] = [
    # --- first run (measured) ---
    # ("baseline",       "server",   [],                                 8,  []),
    # ("num_gen_16",     "server",   ["--num-generations", "16"],        16, []),
    # ("no_grad_ckpt",   "server",   ["--no-gradient-checkpointing"],    8,  []),
    # ("max_compl_512",  "server",   ["--max-completion-length", "512"], 8,  []),
    # ("colocate",       "colocate", [],                                 8,  []),
    # --- second run ---
    # bsN_gaM: pure-parallelism test, effective batch held at 64 (= bs * grad_accum)
    # so vLLM gen-batch stays unchanged; only trainer micro-batch parallelism varies.
    ("prefix_caching", "server", [], 8, ["--enable_prefix_caching", "True"]),
    ("bs16_ga4", "server", ["--batch-size", "16", "--grad-accum", "4"], 8, []),
    ("bs32_ga2", "server", ["--batch-size", "32", "--grad-accum", "2"], 8, []),
    ("bs64_ga1", "server", ["--batch-size", "64", "--grad-accum", "1"], 8, []),
    ("async_grpo", "server", ["--async-grpo"], 8, []),
]


def wait_health(timeout: float = 600.0) -> None:
    deadline = time.time() + timeout
    url = f"http://localhost:{VLLM_PORT}/health/"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(5)
    raise RuntimeError(f"vllm-serve not healthy after {timeout}s: {url}")


def start_vllm(extra_args: list[str] | None = None) -> subprocess.Popen:
    extra = extra_args or []
    label = " ".join(extra) if extra else "(default args)"
    print(f"[bench] starting vllm-serve on GPU 0 {label}", flush=True)
    log = (LOGDIR / "vllm.log").open("w")
    cmd = [
        "uv",
        "run",
        "--no-project",
        "--with",
        "trl[vllm]",
        "--with",
        "transformers @ git+https://github.com/huggingface/transformers.git@main",
        "trl",
        "vllm-serve",
        "--model",
        "Qwen/Qwen3-1.7B",
        *extra,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "CUDA_VISIBLE_DEVICES": "0"},
        cwd=str(REPO),
    )
    try:
        wait_health()
    except Exception:
        proc.terminate()
        raise
    print(f"[bench] vllm-serve ready (pid={proc.pid})", flush=True)
    return proc


def stop_vllm(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    print("[bench] stopping vllm-serve", flush=True)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    subprocess.run(["pkill", "-f", "VLLM::EngineCore"], check=False)
    time.sleep(2)


def run_probe(name: str, mode: str, extra: list[str]) -> dict | None:
    cuda = "0" if mode == "colocate" else "1"
    metrics_path = LOGDIR / f"{name}.metrics.json"
    metrics_path.unlink(missing_ok=True)
    log_path = LOGDIR / f"{name}.log"
    cmd = ["uv", "run", "wordle_train.py"]
    if mode == "colocate":
        cmd.append("--colocate")
    cmd += ["--max-steps", str(MAX_STEPS), "--n-prompts", str(N_PROMPTS), "--metrics-out", str(metrics_path)]
    cmd += extra
    print(f"[bench] probe: {name} ({mode}) :: {' '.join(shlex.quote(s) for s in cmd)}", flush=True)
    started = time.time()
    with log_path.open("w") as log:
        rc = subprocess.run(
            cmd,
            check=False,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "CUDA_VISIBLE_DEVICES": cuda},
            cwd=str(REPO),
        ).returncode
    print(f"  rc={rc} elapsed={time.time() - started:.0f}s", flush=True)
    if rc != 0 or not metrics_path.exists():
        print(f"  FAILED, see {log_path}", flush=True)
        return None
    return json.loads(metrics_path.read_text())


def fmt(x: object) -> str:
    if isinstance(x, float):
        return f"{x:.3f}"
    return "FAIL" if x is None else str(x)


def print_table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    sep = "  "
    for i, r in enumerate(rows):
        print(sep.join(c.ljust(w) for c, w in zip(r, widths, strict=True)))
        if i == 0:
            print(sep.join("-" * w for w in widths))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probes", default="", help="Comma-separated probe names to run (default: all)")
    parser.add_argument(
        "--report-only", action="store_true", help="Skip running; just rebuild the table from existing *.metrics.json"
    )
    args = parser.parse_args()

    LOGDIR.mkdir(parents=True, exist_ok=True)
    selected = set(args.probes.split(",")) if args.probes else None
    to_run = [p for p in PROBES if (selected is None or p[0] in selected)]
    vllm_proc: subprocess.Popen | None = None
    current_vllm_args: list[str] | None = None
    if not args.report_only:
        try:
            for name, mode, extra, _, vllm_args in to_run:
                if mode == "server":
                    if vllm_proc is None or vllm_args != current_vllm_args:
                        if vllm_proc is not None:
                            stop_vllm(vllm_proc)
                            time.sleep(5)
                        vllm_proc = start_vllm(vllm_args)
                        current_vllm_args = vllm_args
                elif vllm_proc is not None:
                    stop_vllm(vllm_proc)
                    vllm_proc = None
                    current_vllm_args = None
                    time.sleep(5)
                run_probe(name, mode, extra)
        finally:
            stop_vllm(vllm_proc)

    # Read metrics for ALL known probes (including ones from prior runs).
    headers = ["probe", "mode", "runtime_s", "steps/s", "prompts/s", "completions/s"]
    rows = [headers]
    for name, mode, _, num_gen, _ in PROBES:
        path = LOGDIR / f"{name}.metrics.json"
        if not path.exists():
            rows.append([name, mode, "MISSING", "MISSING", "MISSING", "MISSING"])
            continue
        m = json.loads(path.read_text())
        runtime = m.get("train_runtime")
        steps_s = m.get("train_steps_per_second")
        samp_s = m.get("train_samples_per_second")
        comp_s = samp_s * num_gen if isinstance(samp_s, (int, float)) else None
        rows.append([name, mode, fmt(runtime), fmt(steps_s), fmt(samp_s), fmt(comp_s)])

    print()
    print_table(rows)

    csv = LOGDIR / "results.csv"
    with csv.open("w") as f:
        for r in rows:
            f.write(",".join(r) + "\n")
    print(f"\nResults written to {csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
