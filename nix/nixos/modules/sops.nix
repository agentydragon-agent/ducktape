# sops-nix secret management for NixOS hosts.
# Decrypts age-encrypted secrets at activation time using the host's SSH key.
{
  config,
  inputs,
  pkgs,
  username,
  ...
}:
let
  user = config.users.users.${username};
  bazelrcDir = "${user.home}/.config/bazel";
  atticDir = "${user.home}/.config/attic";
in
{
  imports = [ inputs.sops-nix.nixosModules.sops ];

  sops.age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];
  sops.defaultSopsFile = ../../../secrets/buildbuddy.yaml;

  sops.secrets.buildbuddy_api_key = { };
  # attic_token: sopsFile set per-host (secrets/{host}-attic.yaml)
  sops.secrets.attic_token = { };

  # Write ~/.config/bazel/buildbuddy.bazelrc from the decrypted secret.
  # ~/.bazelrc already has try-import for this path (via home-manager home.nix).
  system.activationScripts.buildbuddy-bazelrc = {
    deps = [ "setupSecrets" ];
    text = ''
      mkdir -p ${bazelrcDir}
      cat > ${bazelrcDir}/buildbuddy.bazelrc <<EOF
      common --remote_header=x-buildbuddy-api-key=$(cat ${config.sops.secrets.buildbuddy_api_key.path})
      build --config=rbe
      EOF
      chown ${username}:users ${bazelrcDir}/buildbuddy.bazelrc
      chmod 600 ${bazelrcDir}/buildbuddy.bazelrc
    '';
  };

  # Write ~/.config/attic/config.toml directly (no `su` needed).
  system.activationScripts.attic-config = {
    deps = [ "setupSecrets" ];
    text = ''
      mkdir -p ${atticDir}
      token=$(cat ${config.sops.secrets.attic_token.path})
      cat > ${atticDir}/config.toml <<EOF
      default-server = "main"

      [servers.main]
      endpoint = "https://cache.allegedly.works"
      token = "$token"
      EOF
      chown -R ${username}:users ${atticDir}
      chmod 600 ${atticDir}/config.toml
    '';
  };
}
