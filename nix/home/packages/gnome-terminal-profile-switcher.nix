# gnome-terminal-profile-switcher: Switch GNOME Terminal profiles
# Installed from CI-built wheel via GitHub Releases
#
# TODO: Fold this into the ducktape wheel once dbus-python/pygobject deps are sorted
{
  lib,
  pkgs,
}: let
  # Fetch wheel from GitHub Releases
  wheelSrc = pkgs.fetchurl {
    url = "https://github.com/agentydragon/ducktape/releases/download/gnome-terminal-profile-switcher-latest/gnome_terminal_profile_switcher-latest-py3-none-any.whl";
    # Placeholder hash - will be updated after first CI build
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };

  gnome-terminal-profile-switcher = pkgs.python3Packages.buildPythonApplication {
    pname = "gnome-terminal-profile-switcher";
    version = "latest";
    format = "wheel";

    src = wheelSrc;

    propagatedBuildInputs = with pkgs.python3Packages; [
      absl-py
      dbus-python
      pycairo
      pygobject3
    ];

    # Disable checks - wheel is tested in CI
    doCheck = false;

    meta = {
      description = "Switch GNOME Terminal profiles programmatically";
      homepage = "https://github.com/agentydragon/ducktape";
      license = lib.licenses.agpl3Only;
      mainProgram = "switch-gnome-terminal-profile";
    };
  };
in
  gnome-terminal-profile-switcher
