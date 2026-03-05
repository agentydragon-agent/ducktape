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
  shortSha = "322bd4ae";
in
pkgs.stdenv.mkDerivation {
  pname = "kubespand";
  version = shortSha;

  src = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/kubespand-${shortSha}/kubespand";
    # After updating shortSha, set to lib.fakeHash and rebuild to get new hash
    hash = "sha256-LQoV5LbDY2IJQc78PlT7ekiCm6PkjDSxdPKFUamTINY=";
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
