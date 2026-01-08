# git-commit-ai: AI-powered git commit message generator
# Installed from CI-built wheel via GitHub Releases
{
  lib,
  pkgs,
}: let
  # Use system default Python (3.13 in nixpkgs 25.11)
  # Wheel is py3-none-any so compatible with any Python 3.x
  compact-json = pkgs.callPackage ./compact-json.nix {};

  # Fetch wheel directly with fetchurl - flake inputs don't preserve the .whl filename
  # which breaks the wheel install hook
  wheelSrc = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/git-commit-ai-latest/git_commit_ai-latest-py3-none-any.whl";
    hash = "sha256-fpVjbZG/OYXkbmyu2RICiVTBrZz/X7ItusLHFTVihrw=";
  };

  git-commit-ai = pkgs.python3Packages.buildPythonApplication {
    pname = "git-commit-ai";
    version = "latest";
    format = "wheel";

    src = wheelSrc;

    propagatedBuildInputs = with pkgs.python3Packages; [
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

    # Disable checks - wheel is tested in CI
    doCheck = false;

    # No pythonImportsCheck: buildPythonApplication is for executables only,
    # modules aren't made importable by design (see nixpkgs Python docs)

    meta = {
      description = "AI-powered git commit message generator";
      homepage = "https://github.com/agentydragon/ducktape";
      license = lib.licenses.agpl3Only;
      mainProgram = "git-commit-ai";
    };
  };
in
  git-commit-ai
