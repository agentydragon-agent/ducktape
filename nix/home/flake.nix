{
  description = "Home Manager configurations for agentydragon's machines";

  inputs = {
    # Pinned to nixpkgs-unstable as of 2025-12-08
    nixpkgs.url = "github:NixOS/nixpkgs/a672be65651c80d3f592a89b3945466584a22069";

    # Stable nixpkgs (23.11)
    nixpkgs-stable.url = "github:NixOS/nixpkgs/nixos-23.11";

    # Home Manager pinned to master as of 2025-12-08
    home-manager = {
      url = "github:nix-community/home-manager/e5b1f87841810fc24772bf4389f9793702000c9b";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Pinned to nix-colors main as of 2025-12-08
    nix-colors.url = "github:Misterio77/nix-colors/b01f024090d2c4fc3152cd0cf12027a7b8453ba1";

    # nixGL for OpenGL support in non-NixOS systems
    nixGL = {
      url = "github:guibou/nixGL/main";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    claude-code-router.url = "github:agentydragon/claude-code-router/2b7c2ca764f74fd80a6c8b85495df7793282758d";
  };

  outputs = {
    self,
    nixpkgs,
    nixpkgs-stable,
    home-manager,
    nix-colors,
    claude-code-router,
    nixGL,
  }: let
    system = "x86_64-linux";

    # Helper to create home configuration
    mkHome = {
      hostname,
      enableGui ? true,
      enableKube ? true,
      extraModules ? [],
    }: let
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
      };

      oldPkgs = import nixpkgs-stable {
        inherit system;
        config.allowUnfree = true;
      };

      unstablePkgs = pkgs; # Both use the same nixpkgs for now

      solarizedLight = nix-colors.colorSchemes.solarized-light;
      solarizedDark = nix-colors.colorSchemes.solarized-dark;

      terminalFont = {
        family = "JetBrainsMono Nerd Font";
        size = 11;
      };
    in
      home-manager.lib.homeManagerConfiguration {
        inherit pkgs;

        modules =
          [
            claude-code-router.homeManagerModules.claude-code-router
            ./hosts/${hostname}.nix
            {
              _module.args = {
                inherit
                  enableGui
                  enableKube
                  oldPkgs
                  unstablePkgs
                  nix-colors
                  solarizedLight
                  solarizedDark
                  terminalFont
                  ;
                nixGLPackages = nixGL.packages.${system};
              };
            }
          ]
          ++ extraModules;
      };
  in {
    homeConfigurations = {
      # Main laptop (ThinkPad X1 Extreme)
      agentydragon = mkHome {
        hostname = "agentydragon";
        enableGui = true;
        enableKube = true;
      };

      # GPD Win Max 2 laptop
      gpd = mkHome {
        hostname = "gpd";
        enableGui = true;
        enableKube = true;
      };

      # Wyrm desktop VM on atlas
      wyrm = mkHome {
        hostname = "wyrm";
        enableGui = true;
        enableKube = true;
      };

      # NixOS VM
      nixos-vm = mkHome {
        hostname = "nixos-vm";
        enableGui = true;
        enableKube = false;
      };

      # VPS server (minimal, no GUI)
      vps = mkHome {
        hostname = "vps";
        enableGui = false;
        enableKube = false;
      };
    };
  };
}
