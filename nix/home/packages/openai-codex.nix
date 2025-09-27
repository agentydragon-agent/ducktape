{ lib, stdenv, fetchurl, nodejs_20, makeWrapper }:

stdenv.mkDerivation rec {
  pname = "openai-codex";
  version = "0.42.0";

  src = fetchurl {
    url = "https://registry.npmjs.org/@openai/codex/-/codex-${version}.tgz";
    hash = "sha256-iEDfmSfEoXkjurYApjfbU3rZe6UU/3MNAHhQbiWf7FM=";
  };

  nativeBuildInputs = [ makeWrapper ];

  unpackPhase = ''
    tar -xzf $src
  '';

  installPhase = ''
    mkdir -p $out/lib/codex
    cp -r package/* $out/lib/codex/

    # Create the wrapper script
    mkdir -p $out/bin
    makeWrapper ${nodejs_20}/bin/node $out/bin/codex \
      --add-flags "$out/lib/codex/bin/codex.js"

    # Ensure the binary is executable
    chmod +x $out/lib/codex/vendor/*/codex/codex 2>/dev/null || true
    chmod +x $out/lib/codex/vendor/*/path/path 2>/dev/null || true
  '';

  meta = with lib; {
    description = "OpenAI Codex CLI - Lightweight coding agent for your terminal";
    homepage = "https://github.com/openai/codex";
    license = licenses.mit;
    maintainers = [ ];
    platforms = platforms.all;
    mainProgram = "codex";
  };
}