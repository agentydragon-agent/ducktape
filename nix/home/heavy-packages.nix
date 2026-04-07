# Large creative/productivity packages (not essential for development).
# Currently not installed by any host — kept as a reference list.
{
  heavyPackages =
    pkgs: with pkgs; [
      # Creative/CAD
      freecad
      openscad
      xournalpp # Note-taking and PDF annotation

      # Graphics/Audio editing
      gimp
      krita
      inkscape # Vector graphics editor
      audacity

      # Development & Analysis
      vscode # IDE (~400MB)
      wireshark # Network analyzer

      # Media & Downloads
      vlc # Full-featured media player
      transmission_4-gtk # BitTorrent client

      # Web browsers
      google-chrome # Chrome browser

      # Communication (Electron apps)
      discord # Gaming/community chat
      element-desktop # Matrix client

      # Future additions could include:
      # blender      # 3D modeling
      # darktable    # Photo workflow
      # kdenlive     # Video editing
      # ardour       # DAW
      # libreoffice  # Office suite
      # obs-studio   # Streaming/recording
      # steam        # Gaming platform
    ];
}
