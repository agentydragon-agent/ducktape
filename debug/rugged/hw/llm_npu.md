# LLM Inference — NPU (OpenVINO GenAI)

**Goal**: Run small LLMs on the NPU for background/offline inference.

**Hardware**: Lunar Lake NPU (~45 TOPS int8, "Intel AI Boost"). NixOS module:
<nix/nixos/modules/local_llm_npu/default.nix>.

## Current setup — testing

Uses `openvino_genai.LLMPipeline` (the only path that works on NPU — `optimum-intel`
exports dynamic shapes which the NPU compiler rejects, see
[openvinotoolkit/openvino#34617](https://github.com/openvinotoolkit/openvino/issues/34617)).

Pip venv with `openvino-genai`. Model storage: `/var/lib/local-llm/openvino`.

```bash
npu-llm setup                                          # one-time: create pip venv
npu-llm pull OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov    # download pre-converted model
npu-llm chat Qwen2.5-1.5B-Instruct-int4-ov             # interactive chat on NPU
npu-llm bench Qwen2.5-1.5B-Instruct-int4-ov            # benchmark tok/s
npu-llm server Qwen2.5-1.5B-Instruct-int4-ov           # API on :11435
```

Pre-converted models: [OpenVINO HuggingFace NPU collection](https://huggingface.co/collections/OpenVINO/llms-optimized-for-npu).

Expected performance: **~8-10 tok/s** for 7-8B int4 models on Lunar Lake NPU.

## NixOS packaging details

The pip `openvino` package ships the NPU plugin (`libopenvino_intel_npu_plugin.so`)
but NOT the NPU compiler (`libopenvino_intel_npu_compiler.so`). The nix module
extracts the compiler from Intel's OpenVINO archive tarball and patches it with
`autoPatchelfHook` (deps: `libtbb`, `libzstd`, `libstdc++`). The patched `.so` is
symlinked into the venv at runtime.

The wrapper also adds `intel-npu-driver` and `level-zero` to `LD_LIBRARY_PATH` so
OpenVINO can discover the NPU device via Level Zero.

## NPU constraints

- **Greedy decoding only** (`do_sample=False`) — beam search not supported
- **Static shapes required** — `LLMPipeline` handles this internally
- **Context length**: up to 8K tokens
- **No existing LLM server** (ollama, vLLM, etc.) supports NPU as of April 2026
