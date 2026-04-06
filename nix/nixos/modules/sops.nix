# sops-nix secret management for NixOS hosts.
# Decrypts age-encrypted secrets at activation time using the host's SSH key.
# Used by k8s-worker-sops.nix for nebula keys and k8s bootstrap tokens.
{
  inputs,
  ...
}:
{
  imports = [ inputs.sops-nix.nixosModules.sops ];

  sops.age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];
}
