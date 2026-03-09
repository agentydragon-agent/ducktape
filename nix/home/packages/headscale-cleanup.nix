# headscale-cleanup: CLI tool for cleaning up stale Headscale nodes
# Wheel fetched as a flake input (headscale-cleanup-wheel) from GitHub Releases.
# To update: nix flake lock --update-input headscale-cleanup-wheel ./nix
{
  lib,
  pkgs,
  headscale-cleanup-wheel,
}:
pkgs.python3Packages.buildPythonApplication {
  pname = "headscale-cleanup";
  version = "latest";
  format = "wheel";

  src = headscale-cleanup-wheel;

  propagatedBuildInputs = with pkgs.python3Packages; [
    structlog
    typer
  ];

  # Disable checks - wheel is tested in CI
  doCheck = false;

  meta = {
    description = "CLI tool for cleaning up stale Headscale nodes";
    homepage = "https://github.com/agentydragon/ducktape";
    license = lib.licenses.agpl3Only;
    mainProgram = "headscale-cleanup";
  };
}
