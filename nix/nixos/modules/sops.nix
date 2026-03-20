# sops-nix secret management for NixOS hosts.
# Decrypts age-encrypted secrets at activation time using the host's SSH key.
{
  config,
  inputs,
  username,
  ...
}:
let
  user = config.users.users.${username};
  bazelrcDir = "${user.home}/.config/bazel";
in
{
  imports = [ inputs.sops-nix.nixosModules.sops ];

  sops.age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];
  sops.defaultSopsFile = ../../../secrets/buildbuddy.yaml;

  sops.secrets.buildbuddy_api_key = { };

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
}
