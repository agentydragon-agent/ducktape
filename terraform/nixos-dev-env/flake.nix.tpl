{
  description = "Home Manager configuration for ${hostname}";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-${nixos_channel}";
    home-manager = {
      url = "github:nix-community/home-manager${nixos_channel != "unstable" ? "/release-" : "/"}${nixos_channel}";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    ducktape.url = "${ducktape_repo}";
  };

  outputs = { nixpkgs, home-manager, ducktape, ... }: {
    homeConfigurations."${username}" = home-manager.lib.homeManagerConfiguration {
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      modules = [
        {
          home = {
            username = "${username}";
            homeDirectory = "/home/${username}";
            stateVersion = "${nixos_channel == "unstable" ? "24.11" : nixos_channel}";
          };

          # Import ducktape home-manager config
          imports = [ ducktape.packages.x86_64-linux.home ];
        }
      ];
    };
  };
}
