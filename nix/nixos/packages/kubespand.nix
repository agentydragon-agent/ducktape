# kubespand + apid: standalone KubeSpan daemon and Talos API proxy for non-Talos Linux.
# Both binaries are bundled in a single tarball fetched as a flake input (kubespand-tar)
# from GitHub Releases.
# To update: nix flake lock --update-input kubespand-tar
{
  lib,
  pkgs,
  kubespand-tar,
}:
pkgs.stdenv.mkDerivation {
  pname = "kubespand";
  version = "latest";

  src = kubespand-tar;
  sourceRoot = ".";

  installPhase = ''
    install -Dm755 kubespand $out/bin/kubespand
    install -Dm755 apid $out/bin/apid
  '';

  meta = {
    description = "Standalone KubeSpan daemon and Talos API proxy for non-Talos Linux";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "kubespand";
    platforms = [ "x86_64-linux" ];
  };
}
