# Gemma 4 on rugged

**Dates tested**: 2026-06-05 through 2026-06-06 local
**Host**: rugged, Intel Lunar Lake, Arc 130V/140V iGPU, Intel AI Boost NPU,
30GiB RAM

## Takeaways

- Google does have its own runtime path: **LiteRT-LM**. Its direct CLI and
  benchmark path is the best Gemma 4 path tested here today, because the
  official E2B `.litertlm` model runs on rugged's Arc GPU and supports
  LiteRT-LM speculative decoding. It is now packaged locally as `.#litert-lm`.
- LiteRT-LM's OpenAI-compatible `serve` mode exists and works for CPU requests,
  but it is not yet a good OpenCode backend on rugged: CPU prefill is too slow
  at agent-context sizes, and GPU serve mode segfaulted in this local Nix build.
- **Ollama is supported, but not Google's only or primary edge runtime**. It is
  useful as a local API/server interface. Upstream `ollama-vulkan` 0.30.5 from
  `nixpkgs-master` now runs beside the older rugged IPEX/Ollama service.
- **OpenVINO on Linux is working on this machine**, but Gemma 4 is not usable on
  the existing llama.cpp OpenVINO/NPU image yet. The model loads and offloads to
  OpenVINO, then fails on prompt compute with a tensor shape mismatch.

Official references:

- <https://developers.googleblog.com/bring-state-of-the-art-agentic-skills-to-the-edge-with-gemma-4/>
- <https://blog.google/innovation-and-ai/technology/developers-tools/multi-token-prediction-gemma-4/>
- <https://github.com/google-ai-edge/LiteRT-LM>
- <https://developers.google.com/edge/litert/next/litert_lm_npu>
- <https://www.intel.com/content/www/us/en/developer/articles/community/litert-unlocks-core-ultra-npu-performance-for-aipc.html>
- <https://ollama.com/library/gemma4/tags>

## Status matrix

| Path                                            | Local status                                        | Notes                                                                                                                                                 |
| ----------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| LiteRT-LM CLI/API, GPU backend                  | **Works**                                           | Best current direct runtime path. Uses Vulkan on rugged's Intel Arc iGPU and supports Gemma 4 speculative decoding/MTP.                               |
| LiteRT-LM OpenAI-compatible server, CPU backend | **Works but too slow**                              | Protocol is usable for `/v1/models` and `/v1/chat/completions`; OpenCode-scale prefill is not practical.                                              |
| LiteRT-LM OpenAI-compatible server, GPU backend | **Crashes**                                         | `model,gpu` in `litert-lm serve` segfaulted with exit 139; this is separate from the working direct GPU CLI path.                                     |
| LiteRT-LM NPU via generic PyPI/Nix CLI          | **Not working**                                     | `--backend=npu` failed locally with the current package and generic Gemma 4 E2B artifact.                                                             |
| LiteRT-LM Intel OpenVINO NPU upstream path      | **Promising, untested locally**                     | Upstream docs list Intel OpenVINO NPU support and a LunarLake-specific Gemma4-2B `.litertlm` artifact. Needs separate Intel dispatch/OpenVINO wiring. |
| Upstream Ollama/Vulkan                          | **Small prompts work; OpenCode-sized prompts fail** | NixOS service on `127.0.0.1:11436`, using `nixpkgs-master` `ollama-vulkan` and `OLLAMA_IGPU_ENABLE=1`.                                                |
| Old IPEX/Ollama container                       | **Too old for Gemma 4**                             | Bundled Ollama is `0.9.3`; Gemma 4 pull requires newer Ollama.                                                                                        |
| llama.cpp/OpenVINO NPU container                | **Loads/offloads but prompt compute fails**         | OpenVINO Linux itself works, but this backend hits a Gemma 4 KV/tensor shape mismatch.                                                                |

## Current Nix wiring

- `flake.nix` has a shared `nixpkgs-master` input for packages newer than
  unstable. The old narrower `nixpkgs-ollama` idea was folded into this.
- <nix/packages/litert-lm.nix> packages `litert-lm-api==0.13.1`,
  `litert-lm-builder==0.13.0`, and `litert-lm==0.13.1` from PyPI. The native
  wheel is auto-patched against nixpkgs `vulkan-loader`.
- <nix/home/hosts/rugged.nix> puts `ducktapePackages.litert-lm` on rugged's
  user PATH and enables the rugged-only OpenCode provider.
- <nix/nixos/hosts/rugged/local_llm_arc.nix> keeps the old IPEX/Ollama
  container on `127.0.0.1:11434`, pinned by digest instead of mutable `latest`.
- The same NixOS module runs upstream `ollama-vulkan` from `nixpkgs-master` on
  `127.0.0.1:11436`, with separate model storage under
  `/var/lib/local-llm/ollama-upstream`.
- That upstream Ollama service sets `OLLAMA_IGPU_ENABLE=1` so the integrated
  Lunar Lake GPU is used, and `OLLAMA_CONTEXT_LENGTH=131072` so
  OpenAI-compatible clients get the model's advertised context by default.
- <nix/home/opencode/default.nix> exposes the upstream Ollama service to
  OpenCode as provider `rugged`, model `gemma4:e2b-it-qat`. This is wired only
  for rugged and has a TODO to expose it through an authenticated in-cluster
  route if it becomes useful.

## LiteRT-LM

`litert-lm` is not packaged in pinned nixpkgs or nixpkgs master as either a
top-level package or `python313Packages.litert-lm` at the time tested.
`nixpkgs-master` does contain `python313Packages.ai-edge-litert`, but that is
the lower-level LiteRT runtime, not the LiteRT-LM CLI/API package set used here.

The local flake packages the three Google PyPI wheels directly:

- `litert-lm-api==0.13.1`
- `litert-lm-builder==0.13.0`
- `litert-lm==0.13.1`

The native API wheel contains `liblitert-lm.so`; the local derivation patches it
against nixpkgs `vulkan-loader`, so no `LD_LIBRARY_PATH` is needed for Vulkan.
After `sudo nixos-rebuild switch --flake '.#rugged'`, `litert-lm` is on the
user PATH via <nix/home/hosts/rugged.nix>. From the checkout:

```bash
nix build .#litert-lm
HOME=/tmp/litert-lm-home ./result/bin/litert-lm run \
  --from-huggingface-repo=litert-community/gemma-4-E2B-it-litert-lm \
  gemma-4-E2B-it.litertlm \
  --backend=gpu \
  --enable-speculative-decoding=true \
  --temperature=0 \
  --prompt "Reply with exactly: ok"
```

Or after switching rugged:

```bash
env \
  HOME=/tmp/litert-lm-home \
  litert-lm run \
  --from-huggingface-repo=litert-community/gemma-4-E2B-it-litert-lm \
  gemma-4-E2B-it.litertlm \
  --backend=gpu \
  --enable-speculative-decoding=true \
  --temperature=0 \
  --prompt "Reply with exactly: ok"
```

Result: returned `ok`.

`--backend=gpu` works through Vulkan. It logs this warning, but text inference
still succeeds:

```text
INFO: Failed to load OpenCL library with dlopen: libOpenCL.so: cannot open shared object file: No such file or directory. Trying ICD loader.
```

### LiteRT-LM OpenAI-compatible server

`litert-lm serve` exposes an OpenAI-compatible local API. It serves
`/v1/models` and `/v1/chat/completions` on port `9379` by default. The server
model name accepts this local extension:

```text
model_id[,backend][,max_tokens]
```

Import the Hugging Face artifact once:

```bash
HOME=/tmp/litert-lm-home \
  litert-lm import \
  --from-huggingface-repo litert-community/gemma-4-E2B-it-litert-lm \
  gemma-4-E2B-it.litertlm \
  gemma4-e2b-it
```

Then run the server:

```bash
HOME=/tmp/litert-lm-home \
  litert-lm serve --host 127.0.0.1 --port 9379
```

Basic model listing returned:

```json
{
  "object": "list",
  "data": [
    { "id": "gemma4-e2b-it", "object": "model", "owned_by": "litert-lm" },
    { "id": "gemma4-e2b-it,gpu", "object": "model", "owned_by": "litert-lm" }
  ]
}
```

Use an explicit CPU + context model spec for larger contexts:

```bash
curl -sS --fail-with-body -X POST http://127.0.0.1:9379/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma4-e2b-it,cpu,32768","messages":[{"role":"user","content":"Reply with exactly: ok"}],"temperature":0,"max_tokens":8,"stream":false}'
```

Server-mode results from 2026-06-06 local:

| Request                                                         | Result                                                                         |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `gemma4-e2b-it` tiny non-stream chat                            | returned `ok`; server initialized CPU backend with default 4096 max tokens     |
| `gemma4-e2b-it,cpu,32768` streaming chat                        | returned OpenAI SSE chunks and `[DONE]`                                        |
| `gemma4-e2b-it,cpu,32768` with an OpenAI `tools` schema         | accepted request and returned `ok`                                             |
| `gemma4-e2b-it,cpu,32768` with about 4k repeated prompt tokens  | returned `ok` in 1:41.72                                                       |
| `gemma4-e2b-it,cpu,32768` with about 22k repeated prompt tokens | timed out after 5:00 with no bytes while the server was still CPU-bound        |
| `gemma4-e2b-it,gpu` tiny chat                                   | server process exited with code 139; kernel logged `.litert-lm-wrap` segfaults |

Conclusion: the API shape is viable for OpenAI-compatible clients, but only the
CPU server path was stable here. The GPU CLI path still works; the GPU server
path is a separate crash. Do not switch OpenCode to LiteRT-LM serve unless the
GPU serve crash is fixed or the use case can tolerate very slow CPU prefill.

### Benchmarks

Command shape:

```bash
env \
  HOME=/tmp/litert-lm-home \
  litert-lm benchmark \
  --from-huggingface-repo=litert-community/gemma-4-E2B-it-litert-lm \
  gemma-4-E2B-it.litertlm \
  --backend=gpu \
  --enable-speculative-decoding=true \
  --prefill-tokens=512 \
  --decode-tokens=256
```

| Backend | Speculative decoding | Prefill/decode tokens | Prefill speed | Decode speed | Init time | TTFT  |
| ------- | -------------------- | --------------------- | ------------- | ------------ | --------- | ----- |
| GPU     | false                | 128 / 64              | 77.55 tok/s   | 39.23 tok/s  | 11.39s    | 1.68s |
| GPU     | true                 | 128 / 64              | 132.26 tok/s  | 37.34 tok/s  | 8.38s     | 0.99s |
| GPU     | false                | 512 / 256             | 467.74 tok/s  | 38.77 tok/s  | 8.41s     | 1.12s |
| GPU     | true                 | 512 / 256             | 837.72 tok/s  | 40.08 tok/s  | 7.22s     | 0.64s |
| CPU     | false                | 128 / 64              | 135.04 tok/s  | 17.81 tok/s  | 1.15s     | 1.00s |
| GPU     | true, Nix pkg        | 128 / 64              | 91.81 tok/s   | 31.89 tok/s  | 20.14s    | 1.43s |

Short-run interpretation: MTP/speculative decoding helps prefill and time to
first token on this model; decode throughput was roughly equal, slightly better
on the longer sample. The Nix package row was a packaging smoke benchmark that
redownloaded/cold-initialized the artifact, so compare it mainly as "the Nix
package works" rather than as a tuned performance run.

### LiteRT-LM NPU status

Upstream LiteRT-LM now documents Intel OpenVINO NPU support and explicitly
lists a Gemma4-2B LunarLake `.litertlm` artifact with 4096 context. Intel also
describes LiteRT/OpenVINO NPU support for Intel Core Ultra across Windows and
Linux.

That is not the path tested above. The local PyPI/Nix CLI run with the generic
`litert-community/gemma-4-E2B-it-litert-lm` artifact did **not** use rugged's
Linux NPU:

```bash
litert-lm run ... --backend=npu
```

fails with:

```text
RuntimeError: NPU is supported only for Intel OpenVINO on Windows. It is expected to install the 'openvino' package and have an NPU available.
```

Interpretation: rugged's **type** of NPU is in the upstream target set now, but
we have not yet nixified or tested the Intel dispatch build plus the
LunarLake-specific `.litertlm` model. See <llm_npu.md> for the older OpenVINO
container path.

## Ollama

Ollama is not Google's LiteRT runtime. It is an API/server/model-management
layer backed by llama.cpp/ggml-style runtimes. For Gemma 4 here, that means
GGUF/QAT model artifacts and Ollama's Vulkan backend rather than Google's
`.litertlm` format.

The existing rugged service is the IPEX-LLM Ollama container from
<nix/nixos/hosts/rugged/local_llm_arc.nix>:

```bash
curl http://127.0.0.1:11434/api/version
# {"version":"0.9.3"}
```

Gemma 4 pulls fail there with "model requires newer Ollama".

Pinned nixpkgs had Ollama `0.21.1`; nixpkgs master had `0.30.5`; upstream
GitHub latest was `v0.30.6` at the time tested. Rugged now has a dedicated
`nixpkgs-master` flake input wired through
<nix/nixos/hosts/rugged/local_llm_arc.nix>. It runs upstream `ollama-vulkan` on
`127.0.0.1:11436`, beside the IPEX/Ollama service on `127.0.0.1:11434`.

After `nix flake update` on 2026-06-05 local, refreshed `nixpkgs` still had
Ollama `0.21.1` and refreshed `nixpkgs-unstable` had Ollama `0.24.0`. A
temporary Ollama `0.24.0` server on `127.0.0.1:11437` rejected
`gemma4:e2b-it-qat` with "requires a newer version of Ollama", so the
`nixpkgs-master` pin is still needed for Gemma 4.

A temporary `0.30.5` Nix server could pull and run the smaller QAT model, but
it saw CPU only in the ad-hoc test:

```bash
nix shell github:NixOS/nixpkgs/master#ollama -c env \
  OLLAMA_HOST=127.0.0.1:11436 \
  OLLAMA_MODELS=/tmp/gemma4-ollama-030-models \
  OLLAMA_DEBUG=INFO \
  ollama serve

curl -sS --fail-with-body -X POST http://127.0.0.1:11436/api/pull \
  -H 'Content-Type: application/json' \
  -d '{"name":"gemma4:e2b-it-qat","stream":false}'

curl -sS --fail-with-body -X POST http://127.0.0.1:11436/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma4:e2b-it-qat","prompt":"Reply with exactly: ok","stream":false,"options":{"temperature":0,"num_predict":8}}'
```

Result: returned `ok`. Server logs showed CPU-only inference and about 20 tok/s
for the two generated tokens after model load.

First post-switch check: upstream Ollama `0.30.5` started successfully on
`11436` and detected the Intel Vulkan device, then logged:

```text
dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1
```

After setting `OLLAMA_IGPU_ENABLE=1` and switching again, upstream Ollama now
selects the Lunar Lake Vulkan iGPU:

```text
inference compute id=GPU-... library=Vulkan variant=v12 name="Intel(R) Graphics (LNL)"
```

The persistent upstream model directory is separate from the temporary
experiment. Gemma 4 E2B QAT has been pulled there:

```bash
OLLAMA_HOST=127.0.0.1:11436 ollama pull gemma4:e2b-it-qat
OLLAMA_HOST=127.0.0.1:11436 ollama run gemma4:e2b-it-qat
```

The first persistent request after service restart loaded the model in about
29.6s. For visible output through the HTTP API, use `/api/chat` with
`"think": false`:

```bash
curl -sS --fail-with-body -X POST http://127.0.0.1:11436/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"gemma4:e2b-it-qat","messages":[{"role":"user","content":"Reply with one short sentence about local inference."}],"stream":false,"think":false,"options":{"temperature":0,"num_predict":64}}'
```

Warm-ish persistent Ollama/Vulkan timings:

| Request                         | Prompt speed | Decode speed | Load duration | Notes                 |
| ------------------------------- | ------------ | ------------ | ------------- | --------------------- |
| `think:false`, 16 output tokens | 67.39 tok/s  | 22.21 tok/s  | 0.75s         | Visible chat response |
| `think:false`, 82 output tokens | 116.29 tok/s | 22.02 tok/s  | 0.76s         | Visible chat response |

The model metadata advertises `gemma4.context_length = 131072`. A direct
`/api/chat` request with `options.num_ctx = 131072` successfully loaded and
returned `ok` on rugged. Ollama logs confirmed:

```text
slot load_model: ... new slot, n_ctx = 131072
slot update_slots: ... n_ctx_slot = 131072
```

That high-context reload took about 56.8s total for a tiny prompt on the test
run; the steady-state decode after load was still fine.

`/api/generate` without `think:false` can return an empty visible `response`
while still spending tokens; prefer `/api/chat` for quick manual checks.

### OpenCode

Rugged Home Manager enables an OpenCode provider for this local server in
<nix/home/opencode/default.nix>. After switching:

```text
/model
```

then select:

```text
rugged/gemma4:e2b-it-qat
```

Provider details:

- base URL: `http://127.0.0.1:11436/v1`
- provider: `@ai-sdk/openai-compatible`
- model: `gemma4:e2b-it-qat`
- context limit: `131072`

As of 2026-06-06 local, this should be treated as experimental for OpenCode.
Small direct Ollama/Vulkan prompts work, but OpenCode's first request was about
20.6k prompt tokens with system instructions, tools, and skills. That is large
enough to crash the Vulkan runner with `vk::DeviceLostError` / `unexpected EOF`
on this host. The Intel GPU was not generally busy afterward; this looked like
a backend/driver failure during prefill, not ordinary GPU load. LiteRT-LM serve
avoids that specific EOF on CPU, but the server path is too slow at OpenCode
scale and its GPU mode segfaulted.

TODO: if this is useful beyond rugged itself, expose the local server through an
authenticated in-cluster route and move the provider out of the rugged-only
Home Manager option.

The current Ollama MTP tag `gemma4:31b-coding-mtp-bf16` is about 64GB, so it was
not attempted on this 30GiB machine.

## OpenVINO NPU

The existing Linux OpenVINO path is the Docker image from <llm_npu.md>:
`llama-openvino:server`.

The downloaded Ollama QAT GGUF was reused directly:

```bash
docker run --rm -d --name llama-npu-gemma4-test \
  --device=/dev/accel --device=/dev/dri \
  -p 127.0.0.1:18080:8080 \
  -v /tmp/gemma4-ollama-030-models:/models:ro \
  --env=GGML_OPENVINO_DEVICE=NPU \
  llama-openvino:server \
  --no-warmup -c 512 \
  -m /models/blobs/sha256-3646b4c147cd235a44d91df1546d3b7d8e29b547dbe4e1f80856419aa455e6fd
```

Positive signal: Gemma 4 E2B QAT loads and offloads to OpenVINO:

```text
load_tensors: offloading 34 repeating layers to GPU
load_tensors: offloaded 36/36 layers to GPU
load_tensors:    OPENVINO0 model buffer size =  1411.27 MiB
```

Blocking failure: the first prompt returns `Compute error`. Logs show:

```text
Can't set the input tensor with index: 3, because the model input (shape=[1,1,2,256]) and the tensor (shape=(1.35.17.256)) are incompatible
```

Retrying with the known OpenVINO single-session settings:

```bash
--env=GGML_OPENVINO_STATEFUL_EXECUTION=1 ... -np 1
```

changed the context shape (`n_seq_max = 1`, `kv_unified = false`) but did not
become ready; it stayed at `srv load_model: initializing slots, n_slots = 1`
while using about one CPU and 11.7GiB RSS.

Conclusion: OpenVINO Linux works on rugged, but the current llama.cpp OpenVINO
backend does not yet handle Gemma 4 E2B QAT's prompt/KV shape correctly on this
NPU path.

### Nix-native OpenVINO status

Pinned nixpkgs OpenVINO is `2025.2.1`; nixpkgs master has `2026.2.0`. Both were
checked against the Intel container. The nixpkgs builds include:

- `libopenvino_intel_npu_plugin.so`
- NPU headers such as `openvino/runtime/intel_npu/level_zero/level_zero.hpp`

They do **not** include `libopenvino_intel_npu_compiler.so`, which is present in
the Intel OpenVINO bundle used by `llama-openvino:server`. That makes a native
Nix package possible, but not just "build llama.cpp against nixpkgs#openvino"
unless the NPU compiler library is packaged or otherwise supplied.

## Current recommendation

For Gemma 4 E2B on rugged today:

1. Use **LiteRT-LM GPU with speculative decoding** for Google's supported direct
   local runtime path and MTP.
2. Use **Ollama 0.30.x Vulkan** for small local API checks. It works on the
   Intel iGPU for tiny prompts, but it is not yet stable for OpenCode-sized
   Gemma 4 prompts on rugged.
3. Use **LiteRT-LM serve CPU** only as a protocol/debug fallback. It speaks the
   right OpenAI-compatible API, but large prompt prefill is too slow for normal
   agent use.
4. Investigate **LiteRT-LM Intel OpenVINO NPU** separately using the upstream
   LunarLake-specific `.litertlm` artifact and Intel dispatch build. This is
   the most plausible route to actually using rugged's NPU for Gemma 4.
5. Keep **OpenVINO NPU** for older small GGUF models; revisit Gemma 4 after
   llama.cpp/OpenVINO updates.

Durable Nix followups:

- If LiteRT-LM stays useful, consider upstreaming the local `litert-lm` Python
  package set to nixpkgs. `ai-edge-litert` alone is not enough for this CLI path.
- Nixify or otherwise package the upstream LiteRT-LM Intel NPU path: fetch the
  LunarLake-specific `.litertlm`, build/include the Intel OpenVINO dispatch
  library, and test `Backend.NPU()` independently from the generic PyPI CLI path.
- Check whether a newer IPEX/Ollama image contains Ollama 0.30.x or newer. The
  service is now pinned by image digest instead of the mutable `latest` tag, so
  refreshing it requires updating <nix/nixos/hosts/rugged/local_llm_arc.nix>.
- Nixify the working `llama-openvino:server` path once the target model set is
  clear. If the goal is an exact NPU-capable replacement, also package the Intel
  OpenVINO bundle's NPU compiler library or use a pinned OCI image.
