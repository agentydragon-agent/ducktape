{
  description = "ducktape: personal infra + HM modules (module-only flake)";

  # No pinned inputs; adopts consumer's nixpkgs/home-manager versions.
  outputs = { self, ... }: {
    homeManagerModules = {
      claude-code-router = import ./home/modules/claude-code-router.nix;
    };
  };
}

