# kubespand: standalone KubeSpan daemon for non-Talos Linux
# Binary fetched as a flake input (kubespand-bin) from GitHub Releases.
# To update: nix flake lock --update-input kubespand-bin ./nix
{
  lib,
  pkgs,
  kubespand-bin,
}:
pkgs.stdenv.mkDerivation {
  pname = "kubespand";
  version = "latest";

  dontUnpack = true;

  installPhase = ''
    install -Dm755 ${kubespand-bin} $out/bin/kubespand
  '';

  meta = {
    description = "Standalone KubeSpan daemon for non-Talos Linux";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "kubespand";
    platforms = [ "x86_64-linux" ];
  };
}
