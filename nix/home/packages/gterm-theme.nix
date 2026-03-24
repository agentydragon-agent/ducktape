# gterm-theme: GNOME Terminal theme follower — copies a named profile's colors to a mutable "Auto" profile
# Wheel fetched as a flake input (gterm-theme-wheel) from GitHub Releases.
{
  lib,
  pkgs,
  gterm-theme-wheel,
}:
pkgs.python3Packages.buildPythonApplication {
  pname = "gterm-theme";
  version = "latest";
  format = "wheel";

  src = gterm-theme-wheel;

  nativeBuildInputs = with pkgs; [
    gobject-introspection
    wrapGAppsHook3
  ];

  buildInputs = with pkgs; [
    glib
    dbus
    cairo
    gtk3
  ];

  propagatedBuildInputs = with pkgs.python3Packages; [
    absl-py
    dbus-python
    pycairo
    pygobject3
  ];

  doCheck = false;
  dontUsePytestCheck = true;

  meta = {
    description = "GNOME Terminal theme follower";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "gterm-theme";
  };
}
