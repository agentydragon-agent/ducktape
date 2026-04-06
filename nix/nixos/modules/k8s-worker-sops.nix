# Wires sops-nix secrets to the k8s-worker and nebula-mesh modules.
# Hosts just set ducktape.k8sWorkerSops.hostname = "iguana"; and get all the
# sops.secrets + module path bindings automatically.
#
# Nebula certs (CA + host) are plaintext PEM in secrets/nebula/ and deployed
# via environment.etc. Only the host private key is SOPS-encrypted (binary
# format in secrets/nebula/{hostname}.sops.key).
{
  config,
  lib,
  ...
}:
let
  cfg = config.ducktape.k8sWorkerSops;
  secretsDir = ../../../secrets;
  nebulaDir = secretsDir + "/nebula";
  k8sWorkerFile = secretsDir + "/k8s-worker.yaml";
in
{
  options.ducktape.k8sWorkerSops = {
    hostname = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Host name used to locate nebula key (secrets/nebula/{hostname}.sops.key).";
    };
  };

  config = lib.mkIf (cfg.hostname != null) {
    # Plaintext nebula certs deployed via /etc/nebula/
    environment.etc."nebula/ca.crt".text = builtins.readFile (nebulaDir + "/ca.crt");
    environment.etc."nebula/host.crt".text = builtins.readFile (nebulaDir + "/${cfg.hostname}.crt");

    # Only the private key needs SOPS decryption (binary format)
    sops.secrets.nebula_host_key = {
      sopsFile = nebulaDir + "/${cfg.hostname}.sops.key";
      format = "binary";
    };

    # K8s CA cert is public — deploy via environment.etc
    environment.etc."kubernetes/pki/ca.crt".text = builtins.readFile (secretsDir + "/k8s-ca.crt");

    # Bootstrap token is the only secret in k8s-worker.yaml
    sops.secrets.k8s_bootstrap_token.sopsFile = k8sWorkerFile;

    ducktape.nebulaMesh = {
      caCertPath = "/etc/nebula/ca.crt";
      hostCertPath = "/etc/nebula/host.crt";
      hostKeyPath = config.sops.secrets.nebula_host_key.path;
    };

    # caCertPath defaults to /etc/kubernetes/pki/ca.crt (deployed above)
    # bootstrapTokenPath defaults to /run/secrets/k8s_bootstrap_token (sops-nix)
  };
}
