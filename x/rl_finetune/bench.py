#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "torch",
#     "trl[vllm]",
#     "transformers @ git+https://github.com/huggingface/transformers.git@main",
#     "datasets",
#     "accelerate",
#     "tensorboard",
#     "nltk",
#     "peft",
# ]
# ///
"""Throughput benchmark for GRPO Wordle training.

In-process driver: loads the base model + LoRA adapter once on GPU 1, snapshots
the initial adapter state, and runs each probe by building a fresh GRPOTrainer
that points at the shared model. Between probes, restores the adapter snapshot
so each probe starts from the same weights. vllm-serve runs in a subprocess on
GPU 0 (lifecycle managed here; restarted only when vLLM args change).
"""

from __future__ import annotations

import os

# Pin trainer to GPU 1 BEFORE any cuda-touching import (torch reads CUDA_VISIBLE_DEVICES
# at first cuda init). vllm-serve subprocesses get CVD=0 via Popen env override below.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

import argparse
import copy
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import torch
import wordle_train as wt
from peft import get_peft_model
from transformers import AutoModelForCausalLM

REPO = Path(__file__).parent
LOGDIR = Path("/tmp/wordle_bench")
VLLM_PORT = 8000
MAX_STEPS = 5
N_PROMPTS = 320  # 5 steps * 64 prompts/step (effective batch held at 64 across probes).

# Each probe: (name, common_kwargs overrides, async_grpo, num_gen for completions/s, vllm-serve flags).
# First-run probes from the prior subprocess-bench remain on disk in /tmp/wordle_bench/*.metrics.json
# and still appear in the report. Uncomment to re-measure (would need the old subprocess driver, since
# the in-process driver doesn't support colocate mode here).
PROBES: list[tuple[str, dict, bool, int, list[str]]] = [
    # --- second run (in-process) ---
    # bsN_gaM: pure-parallelism test, effective batch = bs*ga held at 64.
    # bs >= 16 OOMs on a 32 GB card with 1024-token rollouts and grad_ckpt=True.
    ("prefix_caching", {}, False, 8, ["--enable_prefix_caching", "True"]),
    ("bs2_ga32", {"per_device_train_batch_size": 2, "gradient_accumulation_steps": 32}, False, 8, []),
    ("bs4_ga16", {"per_device_train_batch_size": 4, "gradient_accumulation_steps": 16}, False, 8, []),
    ("bs8_ga8", {"per_device_train_batch_size": 8, "gradient_accumulation_steps": 8}, False, 8, []),
    ("async_grpo", {}, True, 8, []),
]

DEFAULTS: dict = {
    "output_dir": "/tmp/wordle_grpo_output",
    "num_generations": 8,
    "max_completion_length": 1024,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 64,
    "num_train_epochs": 1000,
    "max_steps": MAX_STEPS,
    "learning_rate": 5e-6,
    "bf16": True,
    "gradient_checkpointing": True,
    "chat_template_kwargs": {"enable_thinking": False},
    "max_tool_calling_iterations": wt.MAX_GUESSES,
    "logging_steps": 1,
    "log_completions": True,
    "num_completions_to_print": 4,
    "save_strategy": "no",
    "report_to": "tensorboard",
}


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
        wt.MODEL,
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


def load_shared_model():
    """Load base + LoRA-wrap once. Returns (model, snapshot of trainable params)."""
    print(f"[bench] loading {wt.MODEL} on cuda:0 (CVD=1 → physical GPU 1)", flush=True)
    base = AutoModelForCausalLM.from_pretrained(wt.MODEL, dtype=torch.bfloat16)
    base = base.to("cuda")
    model = get_peft_model(base, wt.DEFAULT_LORA)
    snapshot = {n: p.detach().clone() for n, p in model.named_parameters() if p.requires_grad}
    print(f"[bench] LoRA-wrapped; {len(snapshot)} trainable tensors snapshotted", flush=True)
    return model, snapshot


def restore_snapshot(model, snapshot: dict) -> None:
    with torch.no_grad():
        for n, p in model.named_parameters():
            if n in snapshot:
                p.data.copy_(snapshot[n])


def run_probe(model, snapshot, name: str, overrides: dict, async_grpo: bool) -> dict | None:
    metrics_path = LOGDIR / f"{name}.metrics.json"
    metrics_path.unlink(missing_ok=True)
    log_path = LOGDIR / f"{name}.log"
    print(f"[bench] probe: {name} :: overrides={overrides} async_grpo={async_grpo}", flush=True)
    started = time.time()
    restore_snapshot(model, snapshot)
    common_kwargs = {**DEFAULTS, **overrides}
    try:
        # Tee training output to per-probe log via stdout/stderr redirect at the OS level.
        with log_path.open("w") as log, _RedirectFds(log):
            metrics = wt.train_session(
                common_kwargs,
                model=model,
                peft_config=None,  # already PEFT-wrapped
                n_prompts=N_PROMPTS,
                async_grpo=async_grpo,
                metrics_out=str(metrics_path),
            )
    except Exception as e:
        print(f"  FAILED: {e}; see {log_path}", flush=True)
        return None
    print(f"  done in {time.time() - started:.0f}s", flush=True)
    return metrics


class _RedirectFds:
    """Redirect stdout/stderr at the file-descriptor level so child C/CUDA prints
    (vLLM, NCCL, tqdm via stderr) also land in the per-probe log."""

    def __init__(self, dest_file):
        self.dest_file = dest_file

    def __enter__(self):
        self._saved_out = os.dup(1)
        self._saved_err = os.dup(2)
        os.dup2(self.dest_file.fileno(), 1)
        os.dup2(self.dest_file.fileno(), 2)
        return self

    def __exit__(self, *exc):
        os.dup2(self._saved_out, 1)
        os.dup2(self._saved_err, 2)
        os.close(self._saved_out)
        os.close(self._saved_err)


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

    if not args.report_only:
        model, snapshot = load_shared_model()
        vllm_proc: subprocess.Popen | None = None
        current_vllm_args: list[str] | None = None
        try:
            for name, overrides, async_grpo, _, vllm_args in to_run:
                if vllm_proc is None or vllm_args != current_vllm_args:
                    if vllm_proc is not None:
                        stop_vllm(vllm_proc)
                        time.sleep(5)
                    vllm_proc = start_vllm(vllm_args)
                    current_vllm_args = copy.copy(vllm_args)
                run_probe(model, snapshot, name, overrides, async_grpo)
        finally:
            stop_vllm(vllm_proc)

    # Report: include both first-run (subprocess) and second-run (in-process) results
    # by reading every *.metrics.json on disk. Per-probe num_gen mapping below covers all.
    known_num_gen = {
        "baseline": 8,
        "num_gen_16": 16,
        "no_grad_ckpt": 8,
        "max_compl_512": 8,
        "colocate": 8,
        "prefix_caching": 8,
        "bs2_ga32": 8,
        "bs4_ga16": 8,
        "bs8_ga8": 8,
        "async_grpo": 8,
    }
    headers = ["probe", "runtime_s", "ss_step_s", "ss_compl/s", "raw_compl/s", "min_step", "max_step"]
    rows = [headers]
    for name, num_gen in known_num_gen.items():
        path = LOGDIR / f"{name}.metrics.json"
        if not path.exists():
            rows.append([name, "MISSING", "MISSING", "MISSING", "MISSING", "MISSING", "MISSING"])
            continue
        m = json.loads(path.read_text())
        runtime = m.get("train_runtime")
        ss_step = m.get("steady_state_step_time_mean")
        ss_min = m.get("steady_state_step_time_min")
        ss_max = m.get("steady_state_step_time_max")
        ss_compl = (64 * num_gen) / ss_step if isinstance(ss_step, (int, float)) and ss_step > 0 else None
        raw_compl = m.get("train_samples_per_second")
        raw_compl = raw_compl * num_gen if isinstance(raw_compl, (int, float)) else None
        rows.append([name, fmt(runtime), fmt(ss_step), fmt(ss_compl), fmt(raw_compl), fmt(ss_min), fmt(ss_max)])

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
