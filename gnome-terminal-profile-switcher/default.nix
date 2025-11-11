{pkgs ? import <nixpkgs> {}}:
pkgs.stdenv.mkDerivation {
  pname = "gnome-terminal-profile-switcher";
  version = "0.1.0";

  src = ./.;

  buildInputs = [pkgs.python3];

  installPhase = ''
    mkdir -p $out/bin

    # Create the executable script
    cat > $out/bin/switch_gnome_terminal_profile << EOF
    #!${pkgs.python3}/bin/python3

    import sys
    sys.path.insert(0, '${pkgs.python3Packages.pygobject3}/${pkgs.python3.sitePackages}')
    sys.path.insert(0, '${pkgs.python3Packages.dbus-python}/${pkgs.python3.sitePackages}')
    sys.path.insert(0, '${pkgs.python3Packages.absl-py}/${pkgs.python3.sitePackages}')

    # Import and run the main function from our module
    sys.path.insert(0, '${placeholder "out"}/lib/python')
    from gnome_terminal_profile_switcher import main

    if __name__ == '__main__':
        main()
    EOF

    chmod +x $out/bin/switch_gnome_terminal_profile

    # Install the Python module
    mkdir -p $out/lib/python
    cp -r src/* $out/lib/python/
  '';

  meta = with pkgs.lib; {
    description = "GNOME Terminal profile switcher for Solarized themes";
    license = licenses.mit;
    platforms = platforms.linux;
  };
}
