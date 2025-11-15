{
  description = "Ducktape development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = {
    self,
    nixpkgs,
  }: let
    systems = ["x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin"];
    forAllSystems = nixpkgs.lib.genAttrs systems;
  in {
    devShells = forAllSystems (system: let
      pkgs = nixpkgs.legacyPackages.${system};
      # Pin pre-commit to match CI (.github/workflows/ci.yml uses pre-commit==4.0.1)
      pre-commit-pinned = pkgs.python3Packages.buildPythonApplication rec {
        pname = "pre-commit";
        version = "4.0.1";
        src = pkgs.fetchFromGitHub {
          owner = "pre-commit";
          repo = "pre-commit";
          rev = "v${version}";
          hash = "sha256-xF6FPuLGTMJ0IHkDloZQ4pfN1FlZbAsvJK95fLE+Xdo=";
        };
        propagatedBuildInputs = with pkgs.python3Packages; [
          cfgv
          identify
          nodeenv
          pyyaml
          virtualenv
        ];
        doCheck = false;
      };
    in {
      default = pkgs.mkShell {
        packages = [
          pre-commit-pinned
          pkgs.alejandra
        ];
      };
    });
  };
}
