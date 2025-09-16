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
    python --version
    if ! python -c 'import importlib.util,sys; sys.exit(0 if importlib.util.find_spec("adgn") else 1)'; then
      python -m pip install -U pip setuptools wheel
      python -m pip install -e '.[dev]'
    fi
  '';
}
