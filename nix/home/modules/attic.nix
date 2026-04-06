# Attic binary cache credentials.
# Decrypted from SOPS at home-manager activation time using ~/.ssh/id_ed25519.
{
  config,
  lib,
  ...
}:
let
  cfg = config.ducktape.attic;
  atticDir = "${config.xdg.configHome}/attic";
in
{
  options.ducktape.attic = {
    enable = lib.mkEnableOption "Attic cache credentials";
    sopsFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to the SOPS-encrypted YAML file containing the attic_token.";
    };
  };

  config = lib.mkIf cfg.enable {
    sops.secrets.attic_token = {
      inherit (cfg) sopsFile;
    };

    home.activation.attic-config = config.lib.dag.entryAfter [ "sops-nix" ] ''
      mkdir -p ${atticDir}
      token=$(cat ${config.sops.secrets.attic_token.path})
      cat > ${atticDir}/config.toml <<EOF
      default-server = "main"

      [servers.main]
      endpoint = "https://cache.allegedly.works"
      token = "$token"
      EOF
      chmod 600 ${atticDir}/config.toml
    '';
  };
}
