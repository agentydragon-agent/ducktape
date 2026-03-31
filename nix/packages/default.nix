# Ducktape packages — built from CI-released artifacts (npins/sources.json).
{
  lib,
  pkgs,
  artifacts,
}:
let
  # CI wheels land in the nix store as "source" (no .whl extension).
  # pypaInstallPhase globs *.whl, so we restore the original filename.
  renameWheel =
    name: input:
    pkgs.runCommand name { } ''
      cp ${input} $out
    '';

  # All ducktape wheels follow the same pattern: pname maps to an npins
  # artifact, wheel filename is <pname_underscored>-0.1.0-py3-none-any.whl.
  mkWheel =
    {
      pname,
      description,
      propagatedBuildInputs ? [ ],
      nativeBuildInputs ? [ ],
      buildInputs ? [ ],
      mainProgram ? null,
    }:
    pkgs.python3Packages.buildPythonApplication {
      inherit pname;
      version = "latest";
      format = "wheel";
      src = renameWheel "${
        builtins.replaceStrings [ "-" ] [ "_" ] pname
      }-0.1.0-py3-none-any.whl" artifacts.${pname};
      inherit
        propagatedBuildInputs
        nativeBuildInputs
        buildInputs
        ;
      doCheck = false;
      dontUsePytestCheck = true;
      meta = {
        inherit description;
        homepage = "https://github.com/agentydragon/ducktape";
        license = lib.licenses.agpl3Only;
      }
      // lib.optionalAttrs (mainProgram != null) { inherit mainProgram; };
    };

  # Python packages not in nixpkgs (used as propagatedBuildInputs)
  compact-json = pkgs.callPackage ./compact-json.nix { };
  pyrage = pkgs.callPackage ./pyrage.nix { };
  keysymdef = pkgs.callPackage ./keysymdef.nix { };
  asyncvnc = pkgs.callPackage ./asyncvnc.nix { inherit keysymdef; };
in
{
  ducktape = mkWheel {
    pname = "ducktape";
    description = "CLI tools (git-commit-ai, difftree, gmail-archiver)";
    mainProgram = "git-commit-ai";
    propagatedBuildInputs = with pkgs.python3Packages; [
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
      fastmcp
      mcp
      pyhamcrest
      click
      unidiff
      beautifulsoup4
      google-api-python-client
      google-auth-httplib2
      google-auth-oauthlib
      pydantic-settings
      python-dateutil
      pyyaml
      compact-json
      # skills deps (hetzner-vnc-screenshot)
      hcloud
      pillow
      websockets
      asyncvnc
    ];
  };

  claude-hooks = mkWheel {
    pname = "claude-hooks";
    description = "Claude Code session hooks (statusline, session-start, auth proxy)";
    mainProgram = "claude-hook";
    propagatedBuildInputs =
      with pkgs.python3Packages;
      [
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
      ]
      ++ [
        pkgs.pre-commit
        pyrage
      ];
  };

  gterm-theme = mkWheel {
    pname = "gterm-theme";
    description = "GNOME Terminal theme follower";
    mainProgram = "gterm-theme";
    nativeBuildInputs = with pkgs; [
      gobject-introspection
      wrapGAppsHook3
    ];
    buildInputs = with pkgs; [
      glib
      dbus
      cairo
      gtk3
    ];
    propagatedBuildInputs = with pkgs.python3Packages; [
      absl-py
      dbus-python
      pycairo
      pygobject3
    ];
  };

  # Standalone packages (not wheels)

  tana = pkgs.callPackage ./tana.nix { };
  gmail-mcp = pkgs.callPackage ./gmail-mcp.nix { };
  bebas-neue-font = pkgs.callPackage ./bebas-neue-font.nix { };

  bbapi = pkgs.stdenv.mkDerivation {
    pname = "bbapi";
    version = "latest";
    src = artifacts.bbapi;
    dontUnpack = true;
    installPhase = ''
      mkdir -p $out/bin
      cp $src $out/bin/bbapi
      chmod +x $out/bin/bbapi
    '';
    meta = {
      description = "BuildBuddy API CLI";
      homepage = "https://github.com/agentydragon/ducktape";
      license = lib.licenses.agpl3Only;
      mainProgram = "bbapi";
      platforms = [ "x86_64-linux" ];
    };
  };

  # Skills data: $out/share/claude-hooks/skills/
  skills = pkgs.runCommand "claude-hooks-skills" { } ''
    mkdir -p $out/share/claude-hooks/skills
    tar xf ${artifacts.skills} -C $out/share/claude-hooks/skills
  '';
}
