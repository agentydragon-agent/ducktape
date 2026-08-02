# public-coder-devbox - headless NixOS VM used by the public-coder OpenClaw
# instance for Git checkouts, direnv, Bazel, BuildBuddy, and tests.
#
# The VM's egress is fenced at the KubeVirt virt-launcher Pod: DNS and the
# public-coder-agent iron-proxy are the only allowed destinations. The proxy CA
# is not copied into Git. trust-manager publishes the live CA bundle as a
# ConfigMap, KubeVirt attaches that ConfigMap as a read-only guest disk, and
# the service below assembles the runtime CA bundle at boot.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  keys = import ../../../ssh-keys.nix;
  proxyHost = "public-coder-agent-proxy.public-coder-agent.svc.cluster.local";
  proxyUrl = "http://${proxyHost}:8080";
  proxyCaDevice = "/dev/disk/by-id/virtio-pcproxyca";
  proxyCaRuntimeDir = "/run/public-coder-devbox-proxy-ca";
in
{
  imports = [
    ../../modules/vm-hardware.nix
    ../../modules/bazel
  ];

  # KubeVirt's NoCloud seed installs this stable host key before sshd is
  # restarted by cloud-init. The private key remains in the encrypted
  # cloud-init Secret; it is never checked into the repository.
  services.cloud-init = {
    enable = true;
    network.enable = false;
    settings.datasource_list = [ "NoCloud" ];
  };

  services.openssh.hostKeys = lib.mkForce [
    {
      type = "ed25519";
      path = "/etc/ssh/ssh_host_ed25519_key";
    }
  ];
  # The VM is intentionally a root-administered build box. Its egress is
  # still enforced outside the guest by the Cilium policy on virt-launcher.
  services.openssh.settings.PermitRootLogin = lib.mkForce "prohibit-password";

  users.users.root.openssh.authorizedKeys.keys = [ keys.publicCoderDevbox ];

  users.users.coder = {
    isNormalUser = true;
    home = "/home/coder";
    shell = pkgs.zsh;
    openssh.authorizedKeys.keys = [ keys.publicCoderDevbox ];
  };

  environment.systemPackages = with pkgs; [
    htop
    btop
    ripgrep
    fd
    fzf
    jq
    yq
    tree
    pv
    strace
    lsof
    git
    openssl
  ];

  # The ConfigMap is attached by KubeVirt as a small virtio disk with the
  # stable serial `pcproxyca`. Build a complete CA bundle from the live
  # ConfigMap contents rather than committing a generated certificate.
  systemd.services.public-coder-devbox-proxy-ca = {
    description = "Install the live public-coder-agent proxy CA bundle";
    wantedBy = [ "multi-user.target" ];
    after = [ "local-fs.target" ];
    before = [ "network-online.target" ];
    path = [ pkgs.coreutils pkgs.util-linux ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      set -eu
      src="${proxyCaRuntimeDir}/source"
      mkdir -p "$src" "${proxyCaRuntimeDir}"
      mounted=0
      for _ in $(seq 1 60); do
        if mountpoint -q "$src"; then
          mounted=1
          break
        fi
        if mount -o ro "${proxyCaDevice}" "$src" 2>/dev/null; then
          mounted=1
          break
        fi
        sleep 1
      done
      if [ "$mounted" -ne 1 ]; then
        echo "KubeVirt proxy CA ConfigMap disk did not appear at ${proxyCaDevice}" >&2
        exit 1
      fi
      test -s "$src/ca-certificates.crt"
      install -Dm0644 "$src/ca-certificates.crt" "${proxyCaRuntimeDir}/proxy-ca.crt"
      cat /etc/ssl/certs/ca-bundle.crt "${proxyCaRuntimeDir}/proxy-ca.crt" \
        > "${proxyCaRuntimeDir}/ca-bundle.crt"
      umount "$src"
    '';
  };

  # These are intentionally placeholders / non-secret routing settings. The
  # iron-proxy substitutes the real GitHub credential only on GitHub hosts.
  environment.sessionVariables = {
    HTTP_PROXY = proxyUrl;
    HTTPS_PROXY = proxyUrl;
    http_proxy = proxyUrl;
    https_proxy = proxyUrl;
    NO_PROXY = "127.0.0.1,localhost";
    no_proxy = "127.0.0.1,localhost";
    GH_PAT = "proxy-github-placeholder";
    SSL_CERT_FILE = "${proxyCaRuntimeDir}/ca-bundle.crt";
    NIX_SSL_CERT_FILE = "${proxyCaRuntimeDir}/ca-bundle.crt";
    CURL_CA_BUNDLE = "${proxyCaRuntimeDir}/ca-bundle.crt";
    GIT_SSL_CAINFO = "${proxyCaRuntimeDir}/ca-bundle.crt";
    NODE_EXTRA_CA_CERTS = "${proxyCaRuntimeDir}/ca-bundle.crt";
  };

  users.motd = "public-coder-devbox - NixOS development VM for public-coder-agent\n";
}
