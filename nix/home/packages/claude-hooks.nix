# claude-hooks: Claude Code session hooks (statusline, session-start, auth proxy)
# Wheel fetched as a flake input (claude-hooks-wheel) from GitHub Releases.
{
  lib,
  pkgs,
  claude-hooks-wheel,
  pre-commit ? pkgs.pre-commit,
}:
pkgs.python3Packages.buildPythonApplication {
  pname = "claude-hooks";
  version = "latest";
  format = "wheel";

  src = claude-hooks-wheel;

  propagatedBuildInputs =
    (with pkgs.python3Packages; [
      anyio
      cryptography
      fastapi
      httpx
      kubernetes
      mako
      opentelemetry-api
      opentelemetry-exporter-otlp-proto-http
      opentelemetry-sdk
      platformdirs
      psutil
      pydantic
      pydantic-settings
      pygit2
      pyjwt
      pyyaml
      rich
      structlog
      supervisor
      tenacity
      uvicorn
    ])
    # pre-commit is imported as a Python library (pre_commit.*), not just a CLI tool.
    ++ [ pre-commit ];

  # Wheel is already tested in CI via Bazel.
  doCheck = false;
  dontUsePytestCheck = true;

  meta = {
    description = "Claude Code session hooks (statusline, session-start, auth proxy)";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "claude-hook";
  };
}
