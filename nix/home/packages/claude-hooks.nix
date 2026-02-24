# claude-hooks: Claude Code hooks and statusline
# Installed from CI-built wheel via GitHub Releases
#
# To update: change shortSha to new 8-char commit SHA, set hash to lib.fakeHash,
# run home-manager switch to get the new hash, then update hash.
{
  lib,
  pkgs,
}:
let
  # 8-char commit SHA from GitHub release tag
  shortSha = "8f52f25d";

  # Fetch wheel directly with fetchurl
  wheelSrc = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/claude-hooks-${shortSha}/claude_hooks-0.1.0-py3-none-any.whl";
    # After updating shortSha, set to lib.fakeHash and rebuild to get new hash
    hash = "sha256-tg2fFSfHBe13NdNfe119EofzvNA91bB4R68nJLO1dyA=";
  };
in
pkgs.python3Packages.buildPythonApplication {
  pname = "claude-hooks";
  version = "latest";
  format = "wheel";

  src = wheelSrc;

  propagatedBuildInputs = with pkgs.python3Packages; [
    cryptography
    httpx
    mako
    opentelemetry-api
    opentelemetry-exporter-otlp-proto-http
    opentelemetry-sdk
    platformdirs
    psutil
    pydantic
    pydantic-settings
    pyjwt
    # pyrage not in nixpkgs — only needed by session_start (encrypted secrets),
    # not by claude-statusline which is the primary reason for this package
    pygit2
    pyyaml
    supervisor
    tenacity
  ];

  # Disable checks - wheel is tested in CI
  doCheck = false;

  meta = {
    description = "Claude Code hooks and statusline";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "claude-statusline";
  };
}
