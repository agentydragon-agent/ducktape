{ pkgs, lib, config, inputs, ... }:

{
  # Basic packages available in the shell
  packages = [ pkgs.git pkgs.nodejs_20 ];

  # Python (devenv-managed venv)
  languages.python = {
    enable = true;
    package = pkgs.python311;
    venv.enable = true;
  };

  # Convenience scripts (available inside the dev shell)
  scripts."ui-dev".exec = "npm --prefix ./src/adgn/llm/mini_codex/ui/web run dev -- --host 127.0.0.1 --port 5173";
  scripts."ui-dev".description = "Run Vite dev server for MiniCodex UI (http://127.0.0.1:5173)";

  scripts."ui-build".exec = "npm --prefix ./src/adgn/llm/mini_codex/ui/web run build";
  scripts."ui-build".description = "Build MiniCodex UI assets into ui/static/web";

  scripts."mini-codex-serve".exec = "python -m adgn.llm.mini_codex.cli serve --host 127.0.0.1 --port 8765";
  scripts."mini-codex-serve".description = "Start MiniCodex backend + FastAPI UI server (http://127.0.0.1:8765)";

  # Background processes (start with: `devenv up`)
  processes.vite.exec = "npm --prefix ./src/adgn/llm/mini_codex/ui/web run dev -- --host 127.0.0.1 --port 5173";

  # On shell entry, ensure the project is installed (editable) with dev extras
  # Install into the active devenv-managed venv so `pytest`, `ruff`, etc. are on PATH
  enterShell = ''
    set -e
    python --version

    # Install dev extras directly into this venv (avoid uv's separate .venv)
    python -m pip install -U pip wheel
    python -m pip install -e '.[dev]'
    echo "Tip: run 'devenv up' to start the Vite UI dev server in the background, or use 'ui-dev'/'mini-codex-serve' scripts."
  '';
}
