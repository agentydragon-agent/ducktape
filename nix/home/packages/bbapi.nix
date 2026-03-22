{
  lib,
  pkgs,
  bbapi-binary,
}:
pkgs.stdenv.mkDerivation {
  pname = "bbapi";
  version = "latest";
  src = bbapi-binary;
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
}
