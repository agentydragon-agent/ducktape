{
  description = "ducktape: personal infra + HM modules (module-only flake)";

  # Note: claude-code-router HM module moved to
  # github:agentydragon/claude-code-router and is consumed directly from there.
  outputs = { self, ... }: {
    homeManagerModules = { };
    darwinModules = {
      claude-code-router = import ./nix/darwin/modules/claude-code-router.nix;
    };
  };
}
