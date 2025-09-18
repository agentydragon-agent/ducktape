{ pkgs, lib, config, inputs, ... }:

{
  # Basic packages available in the shell
  packages = [ pkgs.git ];

  # Python (devenv-managed venv)
  languages.python = {
    enable = true;
    package = pkgs.python311;
    venv.enable = true;
  };

  # On shell entry, ensure the project is installed (editable) with dev extras
  # Install into the active devenv-managed venv so `pytest`, `ruff`, etc. are on PATH
  enterShell = ''
    set -e
    python --version

    # Install dev extras directly into this venv (avoid uv's separate .venv)
    python -m pip install -U pip wheel
    python -m pip install -e '.[dev]'
  '';
}
