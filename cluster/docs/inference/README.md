# Inference backends

Docs hub for LLM inference on the cluster. Notes that should outlive any one
deployment go here; runnable scripts live with the workload (`cluster/k8s/ollama/`,
`x/local_llm/`).

## What's here

- <backend_comparison.md> — feature/format/API matrix across llama.cpp, Ollama,
  vLLM, SGLang, TensorRT-LLM, and the rest. Includes current cluster state
  and migration path. Decision document for picking what to run on wyrm2.
- <vllm_history.md> — distilled lessons from the prior wyrm2-host vLLM work
  (Qwen3-Coder OOM saga, AWQ + FP8 KV cache + `--max-num-seqs 32` fix). Read
  before re-attempting vLLM in cluster.
- <benchmarks.md> — known measurements per (backend, model, flags)
  configuration, caveats that bit us, and an off-the-shelf eval runner
  cheat sheet (simple-evals, lm-eval-harness, evalplus, BFCL, …). Update
  rows when you bring up or rerun a config.
- <qwen3_coder_vram_analysis.md> — full VRAM math, debug logs, profiler
  output. Source data for `vllm_history.md`.
- <vllm_container_plan.md> — home-manager systemd-user service plan that
  ran vLLM on wyrm2.
- <kv_cache_quantization.md> — KV cache dtype research (FP16 vs FP8 vs Q8).
- <model_download_history.md> — model search log and download status.
- <reasoning_vs_agentic_coding.md> — model selection research for the
  reasoning vs coding-agent tradeoff.

## Current state (2026-04-28)

- **Cluster inference**: Ollama Deployment on wyrm2, GGUF only, no tensor
  parallel. See <../../k8s/ollama/app/deployment.yaml>.
- **Host experiments**: `x/local_llm/` on wyrm2 (systemd-user + Docker).
  Has working vLLM AWQ scripts but never moved to k8s.

Full table in <backend_comparison.md#current-state-2026-04-28>.

## Tracking

Add new lessons here as we accumulate them. When investigating a specific
incident or migration, write a focused doc and link it from this README.

## TODO

- **Consolidate per-run `bench.py` copies into one shared script.** Each
  `runs/<date>_<name>/` currently carries a `bench.py` snapshot to
  preserve the run-as-commit invariant. As the bench stabilizes, move it
  to e.g. `cluster/docs/inference/bench/bench.py` and have run dirs only
  store a manifest, env, and output. The snapshot invariant can then be
  preserved by recording the bench commit hash in the run README.

## See also

- <../../k8s/ollama/> — current cluster Ollama deployment
- <../../../x/local_llm/> — wyrm2 host scripts (vLLM/Ollama/comfyui)
- <../../README.md#gpu-nvidia> — GPU/CDI runtime stack on wyrm2
