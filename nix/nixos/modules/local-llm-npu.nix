# Local LLM inference on Intel Lunar Lake NPU via OpenVINO GenAI
#
# Uses a pip venv because `optimum-intel` is not in nixpkgs.
#
# First-time setup (run as user):
#   npu-llm setup                              # creates venv, installs deps
#   npu-llm export Qwen/Qwen2.5-1.5B-Instruct  # export model to OpenVINO IR
#   npu-llm chat Qwen/Qwen2.5-1.5B-Instruct    # interactive chat on NPU
#
# Hardware: Intel Lunar Lake NPU (PCI 8086:643e), needs intel_vpu driver +
# /dev/accel/accel0.
{
  config,
  lib,
  pkgs,
  username,
  ...
}:
let
  cfg = config.ducktape.localLlm.npu;

  npu-llm = pkgs.writeShellScriptBin "npu-llm" ''
    export PYTHON_BIN="${pkgs.python313}/bin/python"
    export SCRIPT_DIR="${./.}"
    exec ${pkgs.bash}/bin/bash "${./local-llm-npu.sh}" "$@"
  '';
in
{
  options.ducktape.localLlm.npu = {
    enable = lib.mkEnableOption "Local LLM inference on Intel NPU (OpenVINO)";
  };

  config = lib.mkIf cfg.enable {
    hardware.cpu.intel.npu.enable = true;
    environment.systemPackages = [ npu-llm ];
    users.users.${username}.extraGroups = [ "render" ];
  };
}
