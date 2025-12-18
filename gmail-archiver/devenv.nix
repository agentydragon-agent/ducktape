{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Basic packages available in the shell
  packages = [pkgs.git];

  # Python (devenv-managed venv)
  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = ["dev"];
      };
    };
  };

  # On shell entry, show helpful info
  enterShell = ''
    set -euo pipefail

    python --version
    echo "gmail-archiver environment ready."
    echo "Run: gmail-archiver --help"
  '';
}
