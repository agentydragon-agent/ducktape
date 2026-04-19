# LLM Inference — Arc GPU (SYCL)

**Goal**: Run small LLMs locally for offline/low-latency use (shell helpers, editor
completions, summarization). Separate from cluster ollama at `ollama.allegedly.works`.

**Hardware**: Arc 130V/140V iGPU (SYCL). 30GB RAM.

## Current setup — running

IPEX-LLM Docker container (`intelanalytics/ipex-llm-inference-cpp-xpu`) runs as
`podman-ipex-ollama.service` via `virtualisation.oci-containers`. NixOS module:
<nix/nixos/modules/local_llm_arc/default.nix>.

- API at `http://localhost:11434` (OpenAI-compatible)
- Model storage: `/var/lib/local-llm/ollama`
- Qwen3 4B (Q4_K_M) installed, **26 tok/s on CPU** (2026-04-18)

```bash
# Pull models:
sudo podman exec ipex-ollama /llm/ollama/ollama pull qwen3:4b
# Test:
curl http://localhost:11434/api/generate -d '{"model":"qwen3:4b","prompt":"Hello","stream":false}'
```

**TODO**: Ollama reports `library=cpu` — model runs on CPU, not Arc GPU.
Root cause found: `LD_LIBRARY_PATH` inside the container didn't include `/llm/ollama/`,
so `libggml-sycl.so` and `libggml-base.so` were not found. Fix applied: added
`export LD_LIBRARY_PATH=/llm/ollama:$LD_LIBRARY_PATH` to the container cmd.
Needs verification after rebuild.

**NixOS native ollama blockers** (why container is needed):

- `services.ollama.acceleration` only supports `"cuda"` and `"rocm"` — no `"intel"`
  option ([nixpkgs#327999](https://github.com/NixOS/nixpkgs/issues/327999))
- Intel DPC++/SYCL compiler not in nixpkgs
  ([nixpkgs#367722](https://github.com/NixOS/nixpkgs/issues/367722))

**Good model candidates** for 30GB RAM + Arc 130V:

- Qwen3 4B — strong general reasoning, tool-calling
- Gemma 3 4B — good instruction following
- Phi-4 Mini 3.8B — code/math
- Qwen2.5-Coder 7B — code completion
