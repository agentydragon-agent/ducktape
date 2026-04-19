#!/usr/bin/env bash
# npu-llm: run LLMs on Intel NPU via OpenVINO GenAI
#
# Requires PYTHON_BIN, SCRIPT_DIR, NPU_COMPILER_SO to be set by the nix wrapper.
set -euo pipefail

VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/npu-llm/venv"
MODEL_DIR="/var/lib/local-llm/openvino"
mkdir -p "$MODEL_DIR" 2>/dev/null || true

usage() {
  cat <<EOF
Usage: npu-llm <command> [args]

Commands:
  setup                  Create/update pip venv with openvino-genai
  pull <hf-model-id>     Download pre-converted model from HuggingFace
  chat <model-name>      Interactive chat on NPU
  bench <model-name>     Benchmark tok/s on NPU
  list                   List downloaded models
  server <model-name>    Start OpenAI-compatible API server on port 11435

Models are stored in $MODEL_DIR. Use HuggingFace model IDs from the
OpenVINO NPU-optimized collection, e.g.:
  npu-llm pull OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov
  npu-llm chat Qwen2.5-1.5B-Instruct-int4-ov
EOF
  exit 1
}

ensure_venv() {
  if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "Venv not found. Run: npu-llm setup" >&2
    exit 1
  fi
  # Ensure the nix-patched NPU compiler .so is symlinked into the venv's
  # openvino libs directory (pip ships the plugin but not the compiler)
  local ov_libs
  ov_libs="$(find "$VENV_DIR/lib" -type d -name libs -path "*/openvino/libs" 2>/dev/null | head -1)"
  if [ -n "${NPU_COMPILER_SO:-}" ] && [ -n "$ov_libs" ]; then
    ln -sf "$NPU_COMPILER_SO" "$ov_libs/libopenvino_intel_npu_compiler.so"
  fi
}

model_dir_for() {
  local model_id="$1"
  local model_name
  model_name="$(basename "$model_id")"
  echo "$MODEL_DIR/$model_name"
}

require_model() {
  local out="$1" name="$2"
  if [ ! -d "$out" ]; then
    echo "Model '$name' not found. Run: npu-llm pull <hf-model-id>" >&2
    echo "Available models:" >&2
    ls -1 "$MODEL_DIR" 2>/dev/null || echo "  (none)" >&2
    exit 1
  fi
}

[ $# -lt 1 ] && usage

case "$1" in
  setup)
    echo "Creating venv at $VENV_DIR ..."
    "$PYTHON_BIN" -m venv --clear "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    "$VENV_DIR/bin/pip" install \
      openvino-genai \
      openvino \
      openvino-tokenizers \
      huggingface-hub \
      fastapi \
      uvicorn
    echo "Done. Venv ready at $VENV_DIR"
    ;;
  pull)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    echo "Downloading $2 to $out ..."
    "$VENV_DIR/bin/huggingface-cli" download "$2" --local-dir "$out"
    echo "Done. Run: npu-llm chat $(basename "$2")"
    ;;
  chat)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_model "$out" "$2"
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/chat.py" "$out"
    ;;
  bench)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_model "$out" "$2"
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/bench.py" "$out"
    ;;
  list)
    echo "Models in $MODEL_DIR:"
    ls -1 "$MODEL_DIR" 2>/dev/null || echo "(none)"
    ;;
  server)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_model "$out" "$2"
    echo "Starting OpenAI-compatible server on :11435 with $(basename "$2") on NPU..."
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py" "$out"
    ;;
  *)
    usage
    ;;
esac
