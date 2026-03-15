# ducktape: CLI tools (git-commit-ai, difftree) and Claude Code hooks (statusline, session-start)
# Wheel fetched as a flake input (ducktape-wheel) from GitHub Releases.
# To update: nix flake lock --update-input ducktape-wheel ./nix
{
  lib,
  pkgs,
  ducktape-wheel,
}:
let
  compact-json = pkgs.callPackage ./compact-json.nix { };
in
pkgs.python3Packages.buildPythonApplication {
  pname = "ducktape";
  version = "latest";
  format = "wheel";

  src = ducktape-wheel;

  propagatedBuildInputs = with pkgs.python3Packages; [
    # git-commit-ai deps
    aiodocker
    anyio
    httpx
    jinja2
    mako
    openai
    pydantic
    pygit2
    rich
    structlog
    tenacity
    typer

    # MCP dependencies
    fastmcp
    mcp

    # Testing dependencies (used at runtime for matchers)
    pyhamcrest

    # difftree deps
    click
    unidiff

    # gmail_archiver deps
    beautifulsoup4
    # email-reply-parser not in nixpkgs — lazily imported
    google-api-python-client
    google-auth-httplib2
    google-auth-oauthlib
    python-dateutil

    # claude_hooks deps
    cryptography
    opentelemetry-api
    opentelemetry-exporter-otlp-proto-http
    opentelemetry-sdk
    platformdirs
    psutil
    pydantic-settings
    pyjwt
    # pyrage not in nixpkgs — lazily imported in secrets_setup.py,
    # so CLI mode (statusline, session_start) works without it
    pyyaml
    supervisor

    # Not in nixpkgs - from overlay
    compact-json
  ];

  # Disable checks - wheel is tested in CI
  doCheck = false;

  meta = {
    description = "CLI tools (git-commit-ai, difftree) and Claude Code hooks (statusline, session-start)";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "git-commit-ai";
  };
}
