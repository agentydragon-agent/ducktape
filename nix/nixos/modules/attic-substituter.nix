# Wires `cache.allegedly.works` (Attic) as a NixOS substituter for the
# nix-daemon. Decrypts a per-host reader JWT from SOPS, renders an
# `/etc/nix/attic-netrc` template, and points `nix.settings.netrc-file` at
# it so the daemon can authenticate to the cache for both `main` (public
# closures) and `gaffer` (gaffer-private artifacts) namespaces.
#
# The `gaffer` cache is a regular substituter (not required) — Nix falls
# back to local build for closures the cache can't serve. drivectl/drivefs
# closures are not buildable on hosts (no Bazel, no source), so realization
# of those specific paths fails when the cache is unreachable; unrelated
# builds still proceed. See plans/token-minting-i-think-scalable-moth.md.
{
  config,
  lib,
  ...
}:
let
  cfg = config.ducktape.attic-substituter;
in
{
  options.ducktape.attic-substituter = {
    enable = lib.mkEnableOption "Attic substituters for cache.allegedly.works";

    sopsFile = lib.mkOption {
      type = lib.types.path;
      description = "SOPS file with an `attic_token` field (per-host reader JWT, scoped main:r,gaffer:r).";
    };
  };

  config = lib.mkIf cfg.enable {
    sops.secrets.attic_token = {
      inherit (cfg) sopsFile;
    };

    sops.templates."attic-netrc" = {
      content = ''
        machine cache.allegedly.works password ${config.sops.placeholder.attic_token}
      '';
      mode = "0400";
      owner = "root";
    };

    nix.settings = {
      # Both caches default-priority 40 — lower than cache.nixos.org (40),
      # equal weight; substituter best-effort, no failure if unreachable.
      substituters = [
        "https://cache.allegedly.works/main?priority=40"
        "https://cache.allegedly.works/gaffer?priority=40"
      ];
      trusted-public-keys = [
        "cache.allegedly.works-1:OX/cis8G1W13DALkGvhdUZ1OY3yGATbXw8+tIc8J7oA="
        # gaffer cache: created by the bootstrap Job in
        # cluster/k8s/nix-cache/bootstrap/, signing keypair lives in attic's
        # Postgres DB. Pubkey captured via:
        #   curl -sSf -H "Authorization: Bearer $JWT" \
        #     https://cache.allegedly.works/_api/v1/cache-config/gaffer \
        #     | jq -r .public_key
        # ($JWT is an atticadm-minted admin token with `--pull '*'`.)
        # TODO: nice-to-have — auto-fetch the pubkey post-creation and push
        # it back into this file via the github-secrets-sync-pat PAT (same
        # mechanism the rotator uses for SOPS files). Pubkey only changes
        # on full cluster rebuild, so the manual step is rare.
        "gaffer:Z8sM2kptUUDGk4ARVD/YkcpzWdMgmZX7nVLV5joK7r8="
      ];
      netrc-file = config.sops.templates."attic-netrc".path;
      connect-timeout = 5;
    };
  };
}
