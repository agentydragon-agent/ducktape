{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Python/uv managed by root devenv.nix - this file only handles adgn-specific infra

  # Node.js for frontend build
  packages = [pkgs.nodejs_20];

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
    # Use Nix-provided Playwright browsers (fixes GLIBC compatibility)
    export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
    export PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=true

    echo "Tip: run 'devenv up' to start Vite UI dev server, or use 'ui-dev'/'agent-serve' scripts."
  '';
}
