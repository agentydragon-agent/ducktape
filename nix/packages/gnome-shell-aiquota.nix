{
  artifacts,
  pkgs,
}:
pkgs.stdenv.mkDerivation {
  pname = "gnome-shell-extension-aiquota";
  version = "1";
  src = artifacts."gnome-shell-aiquota";

  nativeBuildInputs = [
    pkgs.jq
    pkgs.unzip
  ];

  unpackPhase = ''
    runHook preUnpack
    mkdir source
    unzip "$src" -d source
    cd source
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    uuid=$(jq -r '.uuid' metadata.json)
    mkdir -p "$out/share/gnome-shell/extensions/$uuid"
    cp -r . "$out/share/gnome-shell/extensions/$uuid"
    runHook postInstall
  '';

  passthru.extensionUuid = "aiquota@allegedly.works";
}
