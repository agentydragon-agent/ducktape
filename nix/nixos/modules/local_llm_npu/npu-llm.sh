#!/usr/bin/env bash
# npu-llm: manage OpenVINO GenAI models on Intel NPU
#
# Requires PYTHON_BIN and SCRIPT_DIR to be set by the nix wrapper.
set -euo pipefail

VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/npu-llm/venv"
MODEL_DIR="/var/lib/local-llm/openvino"
mkdir -p "$MODEL_DIR" 2>/dev/null || true

usage() {
  cat <<EOF
Usage: npu-llm <command> [args]

Commands:
  setup               Create/update pip venv with OpenVINO + optimum-intel
  export <model-id>   Export HuggingFace model to OpenVINO IR
  chat <model-id>     Interactive chat with exported model on NPU
  bench <model-id>    Benchmark model on NPU
  list                List exported models
  server <model-id>   Start OpenAI-compatible API server on port 11435
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
  local ov_libs="$VENV_DIR/lib/python3.13/site-packages/openvino/libs"
  if [ -n "${NPU_COMPILER_SO:-}" ] && [ -d "$ov_libs" ]; then
    ln -sf "$NPU_COMPILER_SO" "$ov_libs/libopenvino_intel_npu_compiler.so"
  fi
}

model_dir_for() {
  local model_id="$1"
  local model_name
  model_name="$(basename "$model_id")"
  echo "$MODEL_DIR/$model_name"
}

require_exported() {
  local out="$1" model_id="$2"
  if [ ! -d "$out" ]; then
    echo "Model not exported. Run: npu-llm export $model_id" >&2
    exit 1
  fi
}

[ $# -lt 1 ] && usage

case "$1" in
  setup)
    echo "Creating venv at $VENV_DIR ..."
    "$PYTHON_BIN" -m venv --clear "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip
    # Install CPU-only torch to avoid downloading ~1.5GB of CUDA deps
    "$VENV_DIR/bin/pip" install \
      torch --index-url https://download.pytorch.org/whl/cpu
    "$VENV_DIR/bin/pip" install \
      openvino \
      'optimum-intel[openvino]' \
      transformers \
      sentencepiece \
      protobuf \
      fastapi \
      uvicorn
    echo "Done. Venv ready at $VENV_DIR"
    ;;
  export)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/export.py" "$2" "$out"
    ;;
  chat)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_exported "$out" "$2"
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/chat.py" "$out"
    ;;
  bench)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_exported "$out" "$2"
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/bench.py" "$out"
    ;;
  list)
    echo "Exported models in $MODEL_DIR:"
    ls -1 "$MODEL_DIR" 2>/dev/null || echo "(none)"
    ;;
  server)
    [ $# -lt 2 ] && usage
    ensure_venv
    out="$(model_dir_for "$2")"
    require_exported "$out" "$2"
    echo "Starting OpenAI-compatible server on :11435 with $(basename "$2") on NPU..."
    exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/server.py" "$out"
    ;;
  *)
    usage
    ;;
esac
