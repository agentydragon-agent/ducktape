{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Python/uv managed by root devenv.nix

  # Native tools and headers needed for wt development
  packages = with pkgs; [
    libgit2 # for pygit2
    pkg-config
    gitstatus # provides gitstatusd binary
  ];
}
