{ pkgs }:
pkgs.stdenv.mkDerivation {
  pname = "gnome-shell-extension-claude-quota";
  version = "1";
  src = ../../gnome/claude_quota;

  nativeBuildInputs = [
    pkgs.jq
    pkgs.glib
  ];

  installPhase = ''
    runHook preInstall
    uuid=$(jq -r '.uuid' metadata.json)
    mkdir -p "$out/share/gnome-shell/extensions/$uuid"
    cp -r . "$out/share/gnome-shell/extensions/$uuid"
    glib-compile-schemas "$out/share/gnome-shell/extensions/$uuid/schemas"
    runHook postInstall
  '';

  passthru.extensionUuid = "claude-quota@allegedly.works";
}
