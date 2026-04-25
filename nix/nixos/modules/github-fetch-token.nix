{
  config,
  lib,
  ...
}:
let
  cfg = config.ducktape.githubFetchToken;
  secretName = "gaffer_private_fetch_token";
  templateName = "nix-github-fetch-token.env";
  templatePath = "/run/secrets/rendered/${templateName}";
in
{
  options.ducktape.githubFetchToken = {
    enable = lib.mkEnableOption "nix-daemon GitHub token environment for authenticated fetches";

    sopsFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to the SOPS-encrypted YAML file containing the GitHub PAT.";
    };
  };

  config = lib.mkIf cfg.enable {
    sops.secrets.${secretName} = {
      inherit (cfg) sopsFile;
      key = "github_token";
    };

    sops.templates.${templateName} = {
      path = templatePath;
      mode = "0400";
      owner = "root";
      group = "root";
      restartUnits = [ "nix-daemon.service" ];
      content = ''
        GITHUB_TOKEN_GAFFER_PRIVATE=${config.sops.placeholder.${secretName}}
      '';
    };

    systemd.services.nix-daemon.serviceConfig.EnvironmentFile = [ templatePath ];
  };
}
