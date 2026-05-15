{
  artifacts,
  pkgs,
}:
pkgs.stdenv.mkDerivation {
  pname = "gnome-shell-extension-claude-quota";
  version = "1";
  src = artifacts."gnome-shell-claude-quota";

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

  passthru.extensionUuid = "claude-quota@allegedly.works";
}
