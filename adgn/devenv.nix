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
  enterShell = ''
    set -e
    python --version
    # Require uv; fail if missing
    uv --version >/dev/null 2>&1

    # Fast, incremental dependency sync + editable install
    uv sync --extra dev
    uv pip install -e .
  '';
}
