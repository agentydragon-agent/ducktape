{ pkgs, lib, config, inputs, ... }:

{
  packages = with pkgs; [
    git
    pkg-config
  ];

  languages.python = {
    enable = true;
    package = pkgs.python311;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = [ "dev" ];
      };
    };
  };

  enterShell = ''
    set -euo pipefail
    python --version
    echo "Tana export devenv ready. Use 'uv run pytest', 'uv run ruff check .', or 'uv run mypy'."
  '';
}
