# NPU — Intel Lunar Lake

**Goal**: Local AI inference (small LLMs, vision tasks).

**Current state**: Kernel driver works, `/dev/accel/accel0` exists, firmware loaded.
NixOS userspace driver enabled (`hardware.cpu.intel.npu.enable = true` in `default.nix`).
OpenVINO detects it as `Intel(R) AI Boost`.

**Smoke test**:

```bash
npu-umd-test  # bundled validation suite
```

## LLM Inference

See <llm_npu.md> for the LLM inference setup using `openvino_genai.LLMPipeline`.

**Key finding**: No existing LLM server (ollama, vLLM, llama.cpp) supports NPU.
The only working path is `openvino_genai.LLMPipeline` with pre-converted models.
`optimum-intel` direct export produces dynamic shapes which the NPU compiler rejects
([openvinotoolkit/openvino#34617](https://github.com/openvinotoolkit/openvino/issues/34617)).

## Known issues

- [nixpkgs#470638](https://github.com/NixOS/nixpkgs/issues/470638) —
  `hardware.cpu.intel.npu.enable` may not be available depending on nixpkgs pin
- pip `openvino` package missing NPU compiler `.so` — extracted from Intel's
  archive tarball in the nix module
- NPU driver version (nixpkgs v1.28.0) may lag upstream (v1.32.0+)
