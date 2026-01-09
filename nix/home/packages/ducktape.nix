# ducktape: CLI tools collection (git-commit-ai, difftree)
# Installed from CI-built wheel via GitHub Releases
{
  lib,
  pkgs,
}: let
  compact-json = pkgs.callPackage ./compact-json.nix {};

  # Fetch wheel directly with fetchurl
  wheelSrc = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/ducktape-latest/ducktape-latest-py3-none-any.whl";
    # Hash will need to be updated after first release
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };

  ducktape = pkgs.python3Packages.buildPythonApplication {
    pname = "ducktape";
    version = "latest";
    format = "wheel";

    src = wheelSrc;

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

      # Not in nixpkgs - from overlay
      compact-json
    ];

    # Disable checks - wheel is tested in CI
    doCheck = false;

    meta = {
      description = "CLI tools collection: git-commit-ai, difftree";
      homepage = "https://github.com/agentydragon/ducktape";
      license = lib.licenses.agpl3Only;
      mainProgram = "git-commit-ai";
    };
  };
in
  ducktape
