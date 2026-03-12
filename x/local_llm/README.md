# Local LLM Inference

Running local LLMs on 2x RTX 5090 (64GB VRAM).

## Backends

| Backend | Port  | Tensor Parallel | Quantization  | Use Case                      |
| ------- | ----- | --------------- | ------------- | ----------------------------- |
| Ollama  | 11434 | No              | GGUF (Q4, Q8) | Easy setup, interactive       |
| vLLM    | 8000  | Yes             | HF, AWQ, GPTQ | Best throughput, long context |

## Quick Start

```bash
cd experimental/local-llm

# Ollama (already running as systemd service)
ollama list
ollama run qwen3-coder-long

# vLLM (tensor parallel)
# First time: uv pip install vllm --system
./start-vllm.sh
```

## Models

See <model-download-list.md> for the full model search log, experiment history, and download status.

See <vram-analysis.md> for detailed VRAM calculations and memory debugging.

## OpenCode Integration

Both backends are configured in opencode. Select model in opencode UI:

- **Qwen3-Coder 30B 131k (local)** - Ollama backend
- **Qwen3-Coder 30B TP2 (vLLM)** - vLLM backend (must start server first)

Config: `nix/home/opencode/default.nix`

## Storage

- Ollama models: `/wyrmhdd/ollama-models`
- HuggingFace cache: `/wyrmhdd/huggingface`

## Creating Ollama Model Variants

```bash
# Extended context variant
ollama create qwen3-coder-long -f Modelfile.qwen3-coder-long

# Or interactively
ollama run qwen3-coder:30b
/set parameter num_ctx 131072
/save qwen3-coder-long
/bye
```
