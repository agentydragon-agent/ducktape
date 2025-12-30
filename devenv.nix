{pkgs, ...}: {
  # Basic packages available in the shell
  # stdenv.cc.cc.lib provides libstdc++.so.6 needed by numpy, etc.
  packages = [
    pkgs.git
    pkgs.bazelisk
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
  ];

  enterShell = ''
    # Add native library paths for C extensions
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    echo "Bazel dev environment ready. Use 'bazel build //...' to build."
  '';
}
