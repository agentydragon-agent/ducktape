{
  description = "Container image spike using nix2container";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    nix2container = {
      url = "github:nlewo/nix2container";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nix2container }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      n2c = nix2container.packages.${system}.nix2container;
    in
    {
      packages.${system} = {

        # --- Simple Python App Image ---
        # Equivalent to: FROM python:3.13-slim + apt-get install curl jq git
        python-app-image = n2c.buildImage {
          name = "python-app";
          tag = "latest";

          # Each entry in copyToRoot becomes part of the root filesystem.
          # nix2container automatically deduplicates store paths into layers.
          copyToRoot = pkgs.buildEnv {
            name = "python-app-root";
            paths = [
              pkgs.python313
              pkgs.curl
              pkgs.jq
              pkgs.git
              pkgs.cacert  # CA certificates
              pkgs.bashInteractive  # Shell for debugging
              pkgs.coreutils  # Basic POSIX utilities
            ];
            pathsToLink = [ "/bin" "/lib" "/etc" "/share" ];
          };

          config = {
            Env = [
              "PYTHONUNBUFFERED=1"
              "PYTHONDONTWRITEBYTECODE=1"
              "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
            ];
            WorkingDir = "/opt/app";
            Cmd = [ "${pkgs.python313}/bin/python3" ];
          };
        };

        # --- E2E Test Image ---
        # Equivalent to: FROM python:3.13-slim + apt-get install default-jdk-headless git
        e2e-test-image = n2c.buildImage {
          name = "e2e-test";
          tag = "latest";

          copyToRoot = pkgs.buildEnv {
            name = "e2e-test-root";
            paths = [
              pkgs.python313
              pkgs.jdk21_headless
              pkgs.git
              pkgs.cacert
              pkgs.bashInteractive
              pkgs.coreutils
            ];
            pathsToLink = [ "/bin" "/lib" "/etc" "/share" ];
          };

          config = {
            Env = [
              "JAVA_HOME=${pkgs.jdk21_headless}"
              "SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt"
            ];
          };
        };

        # --- RBE Worker Image ---
        # See rbe-worker.nix for the full expression.
        # This demonstrates that ALL required packages are available in nixpkgs.
        rbe-worker-image = import ./rbe-worker.nix {
          inherit pkgs n2c;
        };
      };
    };
}
