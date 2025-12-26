{pkgs, ...}: {
  # Basic packages available in the shell
  # stdenv.cc.cc.lib provides libstdc++.so.6 needed by numpy, etc.
  packages = [pkgs.git pkgs.stdenv.cc.cc.lib pkgs.zlib];

  # Python with uv for workspace-wide venv management
  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv = {
      enable = true;
      sync.enable = true;
    };
  };

  enterShell = ''
    # Add native library paths for Python C extensions (numpy, etc.)
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    python --version
  '';
}
