{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # Python/uv managed by root devenv.nix

  enterShell = ''
    echo "Ember devenv ready. Use 'pytest' to run tests."
  '';
}
