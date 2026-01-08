# git-commit-ai: AI-powered git commit message generator
# Installed from CI-built wheel via GitHub Releases
{
  lib,
  pkgs,
  git-commit-ai-wheel,
}: let
  python = pkgs.python312;

  compact-json = pkgs.callPackage ./compact-json.nix {};

  git-commit-ai = python.pkgs.buildPythonApplication {
    pname = "git-commit-ai";
    version = "latest";
    format = "wheel";

    src = git-commit-ai-wheel;

    propagatedBuildInputs = with python.pkgs; [
      # Core dependencies
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

      # Not in nixpkgs - from overlay
      compact-json
    ];

    # Disable checks - wheel doesn't include tests
    doCheck = false;

    pythonImportsCheck = ["git_commit_ai"];

    meta = {
      description = "AI-powered git commit message generator";
      homepage = "https://github.com/agentydragon/ducktape";
      license = lib.licenses.agpl3Only;
      mainProgram = "git-commit-ai";
    };
  };
in
  git-commit-ai
