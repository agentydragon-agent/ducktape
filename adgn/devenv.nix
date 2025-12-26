{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Basic packages available in the shell
  # stdenv.cc.cc.lib provides libstdc++.so.6 needed by numpy, jsonnet, etc.
  packages = [pkgs.git pkgs.nodejs_20 pkgs.stdenv.cc.cc.lib pkgs.zlib];

  # Python (devenv-managed venv)
  languages.python = {
    enable = true;
    package = pkgs.python312;
    uv = {
      enable = true;
      sync = {
        enable = true;
        extras = ["dev" "matrix"];
      };
    };
  };

  # Convenience scripts (available inside the dev shell)
  scripts."ui-dev".exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";
  scripts."ui-dev".description = "Run Vite dev server for Agent UI (http://127.0.0.1:5173)";

  scripts."ui-build".exec = "npm --prefix ./src/adgn/agent/web run build";
  scripts."ui-build".description = "Build Agent UI assets into server/static/web";

  scripts."agent-serve".exec = "python -m adgn.agent.cli serve --host 127.0.0.1 --port 8765";
  scripts."agent-serve".description = "Start Agent backend + FastAPI UI server (http://127.0.0.1:8765)";

  # Background processes (start with: `devenv up`)
  processes.vite.exec = "npm --prefix ./src/adgn/agent/web run dev -- --host 127.0.0.1 --port 5173";

  # On shell entry
  enterShell = ''
    set -euo pipefail

    # Add native library paths for Python C extensions (numpy, jsonnet, etc.)
    export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib:${pkgs.zlib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

    # Use Nix-provided Playwright browsers (fixes GLIBC compatibility)
    export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
    export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true

    python --version
    echo "Tip: run 'devenv up' to start Vite UI dev server, or use 'ui-dev'/'agent-serve' scripts."
  '';
}
