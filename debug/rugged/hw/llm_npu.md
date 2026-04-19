# LLM Inference — NPU (OpenVINO)

**Goal**: Run small LLMs on the NPU for background/offline inference.

**Hardware**: Lunar Lake NPU (~45 TOPS int8). NixOS module:
<nix/nixos/modules/local-llm-npu.nix>.

## Current setup — venv being set up

Uses pip venv with `optimum-intel` (not in nixpkgs). Model storage:
`/var/lib/local-llm/openvino`.

```bash
npu-llm setup                                # one-time: create pip venv
npu-llm export Qwen/Qwen2.5-1.5B-Instruct    # export model to OpenVINO IR
npu-llm chat Qwen/Qwen2.5-1.5B-Instruct      # interactive chat on NPU
npu-llm server Qwen/Qwen2.5-1.5B-Instruct    # API on :11435
```

**TODO**: `npu-llm setup` pip installs CUDA torch (~1.5GB wasted). Use
`--index-url https://download.pytorch.org/whl/cpu` for CPU-only torch.
