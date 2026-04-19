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

  # The pip openvino package ships the NPU plugin but NOT the NPU compiler
  # (libopenvino_intel_npu_compiler.so). The compiler is only in Intel's
  # archive tarball. We extract just that .so and add it to LD_LIBRARY_PATH.
  openvino-npu-compiler = pkgs.stdenv.mkDerivation {
    pname = "openvino-npu-compiler";
    version = "2026.1.2";
    src = pkgs.fetchurl {
      url = "https://storage.openvinotoolkit.org/repositories/openvino/packages/2026.1.2/linux/openvino_toolkit_ubuntu24_2026.1.2.21379.f3a30a671d3_x86_64.tgz";
      hash = "sha256-veDDlRl2RR8dEgowjkCSK7gTyz7B6Bdzwp7z7nyp9vE=";
    };
    nativeBuildInputs = [ pkgs.autoPatchelfHook ];
    buildInputs = [
      pkgs.stdenv.cc.cc.lib # libstdc++
      pkgs.tbb # libtbb.so.12
      pkgs.zstd # libzstd
    ];
    dontBuild = true;
    installPhase = ''
      mkdir -p $out/lib
      cp runtime/lib/intel64/libopenvino_intel_npu_compiler.so $out/lib/
    '';
  };

  npu-llm = pkgs.writeShellScriptBin "npu-llm" ''
    export PYTHON_BIN="${pkgs.python313}/bin/python"
    export SCRIPT_DIR="${./.}"
    export NPU_COMPILER_SO="${openvino-npu-compiler}/lib/libopenvino_intel_npu_compiler.so"
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    exec ${pkgs.bash}/bin/bash "${./npu-llm.sh}" "$@"
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

    # Model storage: /var/lib/local-llm/openvino (shared parent with Arc models)
    systemd.tmpfiles.rules = [
      "d /var/lib/local-llm 0755 root root -"
      "d /var/lib/local-llm/openvino 0755 ${username} root -"
    ];
  };
}
