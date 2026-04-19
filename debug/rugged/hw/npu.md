# NPU — Intel Lunar Lake

**Goal**: Local AI inference (small LLMs, vision tasks).

**Current state**: Kernel driver works, `/dev/accel/accel0` exists, firmware loaded.
NixOS userspace driver enabled (`hardware.cpu.intel.npu.enable = true` in `default.nix`).

**Smoke test**:

```bash
npu-umd-test  # bundled validation suite
```

**LLM inference on NPU**:

Ollama has no NPU support (open issues
[#8281](https://github.com/ollama/ollama/issues/8281),
[#5747](https://github.com/ollama/ollama/issues/5747)).

**NPU inference frameworks** (ranked by maturity):

| Framework              | Maturity    | Model limit | NixOS path               |
| ---------------------- | ----------- | ----------- | ------------------------ |
| **OpenVINO GenAI**     | Best        | ~7-8B int4  | pip venv + kernel module |
| **ipex-llm**           | Moderate    | ~7B int4    | Container likely needed  |
| **llama.cpp OpenVINO** | Low for NPU | ~3B         | Manual OpenVINO install  |
| **NPU Accel Library**  | Stale       | ~7B         | Not recommended          |

1. **OpenVINO GenAI** (`openvino-genai` pip package) — most mature path. Export model
   to OpenVINO IR format via `optimum-intel`, run with `device="NPU"`. Supports Llama
   2/3, Phi-2/3, Qwen 2, Gemma 2B with int4 quantization. On NixOS: install via pip
   in a venv, ensure `intel_vpu` kernel module is loaded.

2. **ipex-llm** — Intel's library has experimental NPU support for Lunar Lake. Uses
   OpenVINO internally. On NixOS: container likely needed due to complex deps
   (oneAPI, OpenVINO, specific PyTorch versions).

3. **llama.cpp + OpenVINO backend** (`-DGGML_OPENVINO=ON`,
   `GGML_OPENVINO_DEVICE=NPU`) — merged upstream April 2026. Best for small models
   (1-3B params), small context (`-c 512`). Validated: Llama-3.2-1B, Phi-3-mini,
   Qwen2.5-1.5B. Supported quantizations: FP16, Q8_0, Q4_0, Q4_1, Q4_K, Q4_K_M.

4. **Intel NPU Acceleration Library** — research/demo project, sparse commits, not
   recommended.

**Lunar Lake NPU has ~45 TOPS int8** — useful for background/offline inference on small
models, not as a primary inference accelerator.

**NixOS blocker**: OpenVINO GenAI needs OpenVINO 2024.0+. nixpkgs has 2025.2.1 (library
only, no CLI tools). The llama.cpp backend needs OpenVINO 2026.x (not yet in nixpkgs).
Practical path: pip venv for OpenVINO GenAI, or wait for nixpkgs bumps.

**Known issue**: [nixpkgs#470638](https://github.com/NixOS/nixpkgs/issues/470638) —
`hardware.cpu.intel.npu.enable` may not be available depending on nixpkgs pin. If so,
add manually:

```nix
hardware.firmware = [ pkgs.intel-npu-driver.firmware ];
hardware.graphics.extraPackages = [ pkgs.intel-npu-driver ];
environment.systemPackages = [ pkgs.level-zero pkgs.intel-npu-driver.validation ];
```
