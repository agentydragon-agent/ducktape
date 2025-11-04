{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Core utilities inside the shell
  packages = [
    pkgs.git
  ];

  # Python environment managed by devenv + uv
  languages.python = {
    enable = true;
    package = pkgs.python311;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = ["dev"];
      };
    };
  };

  enterShell = ''
    set -euo pipefail
    uv sync --extra dev --quiet
    python --version
    echo "Ember devenv ready. Use 'uv run pytest' to run tests."
  '';
}
