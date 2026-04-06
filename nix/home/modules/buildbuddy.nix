# BuildBuddy remote cache/execution credentials.
# Decrypts the API key from SOPS at home-manager activation time using ~/.ssh/id_ed25519,
# then writes ~/.config/bazel/buildbuddy.bazelrc.
{ config, ... }:
let
  bazelrcDir = "${config.xdg.configHome}/bazel";
in
{
  sops.secrets.buildbuddy_api_key = {
    sopsFile = ../../../secrets/buildbuddy.yaml;
  };

  home.activation.buildbuddy-bazelrc = config.lib.dag.entryAfter [ "sops-nix" ] ''
    mkdir -p ${bazelrcDir}
    cat > ${bazelrcDir}/buildbuddy.bazelrc <<EOF
    common --remote_header=x-buildbuddy-api-key=$(cat ${config.sops.secrets.buildbuddy_api_key.path})
    build --config=rbe
    EOF
    chmod 600 ${bazelrcDir}/buildbuddy.bazelrc
  '';
}
