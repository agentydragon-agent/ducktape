{ pkgs, ... }:
{
  # Recommended: devenv-managed Python venv with uv; sync runs only on lock changes.
  languages.python = {
    enable = true;
    version = "3.11";     # or "3.12" if you prefer
    venv.enable = true;    # keep venv under .devenv/state
    uv.enable = true;      # provide uv in the shell
    uv.sync.enable = true; # run `uv sync` during initialisation (cached by direnv)
  };
}
