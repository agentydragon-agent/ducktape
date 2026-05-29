# Atuin shell-history sync. Three pieces wired in one place:
#   - programs.atuin (CLI config + shell integrations)
#   - SOPS-managed E2EE sync key at ${xdg.dataHome}/atuin/key
#   - SOPS-managed server password (shared with the cluster-side
#     atuin-user-provisioner Job — same plaintext seeds the argon2 hash
#     in atuin's users table and authenticates `atuin login` here)
#   - First-run `atuin login` via home-manager activation
#
# After activation each host shares the same encryption key and is logged
# into atuin.allegedly.works, so history flows transparently across machines.
{
  config,
  lib,
  pkgs,
  ...
}:
{
  programs.atuin = {
    enable = true;
    enableBashIntegration = true;
    enableZshIntegration = true;
    flags = [ "--disable-up-arrow" ];
    settings = {
      sync_address = "https://atuin.allegedly.works";
    };
  };

  sops.secrets.atuin_key = {
    sopsFile = ../../../secrets/shared/atuin-key.yaml;
    key = "sync_key";
    path = "${config.xdg.dataHome}/atuin/key";
    mode = "0600";
  };

  sops.secrets.atuin_user_password = {
    sopsFile = ../../../cluster/k8s/user-agentydragon/atuin-user-password.sops.yaml;
    key = "stringData/user_password";
    mode = "0600";
  };

  # First-run login: if no session token yet, exchange password + key for one.
  # `atuin login` writes ${xdg.dataHome}/atuin/session. Failures are tolerated
  # (server outage, offline laptop) so activation stays unblocked — the next
  # `home-manager switch` retries. Sequenced after sops-nix so the secret
  # files exist; the readability guard handles the bootstrap case where
  # sops-nix's systemd unit hasn't run yet.
  home.activation.atuinLogin = lib.hm.dag.entryAfter [ "sops-nix" ] ''
    SESSION="${config.xdg.dataHome}/atuin/session"
    PASS="${config.sops.secrets.atuin_user_password.path}"
    KEY="${config.sops.secrets.atuin_key.path}"
    if [ ! -s "$SESSION" ] && [ -r "$PASS" ] && [ -r "$KEY" ]; then
      ${pkgs.atuin}/bin/atuin login \
        -u agentydragon \
        -p "$(cat "$PASS")" \
        -k "$(cat "$KEY")" \
        || echo "atuin login failed; will retry on next home-manager switch"
    fi
  '';
}
