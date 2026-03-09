# kubespand: standalone KubeSpan daemon for non-Talos Linux
# Installed from CI-built static binary via GitHub Releases
#
# To update: change shortSha to new 8-char commit SHA, set hash to lib.fakeHash,
# run nixos-rebuild to get the new hash, then update hash.
{
  lib,
  pkgs,
}:
let
  # 8-char commit SHA from GitHub release tag (CI-managed)
  shortSha = "e0cb808a";
in
pkgs.stdenv.mkDerivation {
  pname = "kubespand";
  version = shortSha;

  src = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/kubespand-${shortSha}/kubespand";
    hash = "sha256-EGRGO3Tcbvya+/vAB1GKNpOMTFFVWeg/zwicXJ2I+RM=";
    executable = true;
  };

  dontUnpack = true;

  installPhase = ''
    install -Dm755 $src $out/bin/kubespand
  '';

  meta = {
    description = "Standalone KubeSpan daemon for non-Talos Linux";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "kubespand";
    platforms = [ "x86_64-linux" ];
  };
}
