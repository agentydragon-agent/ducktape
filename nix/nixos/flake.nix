{
  description = "NixOS configurations for agentydragon's VMs";

  inputs = {
    # NixOS 25.11 stable release
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";

    home-manager = {
      url = "github:nix-community/home-manager/release-25.11";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Import the home-manager flake for shared config
    ducktape-home = {
      url = "github:agentydragon/ducktape?dir=nix/home&ref=devel";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    self,
    nixpkgs,
    home-manager,
    ducktape-home,
    ...
  } @ inputs: let
    system = "x86_64-linux";

    # Helper to create NixOS configuration for a VM
    mkNixosVm = {
      hostname,
      username ? "user",
      homeManagerHost ? hostname,
      extraModules ? [],
    }:
      nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = {inherit inputs hostname username homeManagerHost;};
        modules =
          [
            ./modules/base.nix
            ./modules/vm-hardware.nix
            ./hosts/${hostname}.nix
            home-manager.nixosModules.home-manager
            {
              home-manager.useGlobalPkgs = true;
              home-manager.useUserPackages = true;
              # Home-manager config will be applied separately via flake
            }
          ]
          ++ extraModules;
      };
  in {
    nixosConfigurations = {
      wyrm2 = mkNixosVm {
        hostname = "wyrm2";
        username = "user";
        homeManagerHost = "nixos-vm";
      };
    };
  };
}
