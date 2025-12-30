{pkgs, ...}: {
  # Basic packages available in the shell
  # stdenv.cc.cc.lib provides libstdc++.so.6 needed by numpy, etc.
  packages = [
    pkgs.git
    pkgs.stdenv.cc.cc.lib
    pkgs.zlib
    pkgs.ninja
    pkgs.pkg-config
    pkgs.dbus
    pkgs.glib
    pkgs.gobject-introspection
    pkgs.cairo
  ];

  # Python with uv for workspace-wide venv management
  languages.python = {
    enable = true;
    package = pkgs.python313;
    uv = {
      enable = true;
      sync.enable = true;
      # Don't use allExtras - it pulls in adgn[gnome] which requires dbus-python
      # and complex system dependencies. Specify needed extras explicitly.
      sync.extras = ["dev"];
    };
  };

  enterShell = ''
    # Add native library paths for Python C extensions (numpy, etc.)
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    python --version
  '';
}
