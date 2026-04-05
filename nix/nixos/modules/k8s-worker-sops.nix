# Wires sops-nix secrets to the k8s-worker and nebula-mesh modules.
# Hosts just set ducktape.k8sWorkerSops.hostname = "iguana"; and get all the
# sops.secrets + module path bindings automatically.
{
  config,
  lib,
  ...
}:
let
  cfg = config.ducktape.k8sWorkerSops;
  secretsDir = ../../../secrets;
  k8sWorkerFile = secretsDir + "/k8s-worker.yaml";
in
{
  options.ducktape.k8sWorkerSops = {
    hostname = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Host name used to locate sops secret files (secrets/{hostname}-nebula.yaml).";
    };
    nebulaFile = lib.mkOption {
      type = lib.types.path;
      description = "Path to the SOPS-encrypted nebula secret file for this host.";
    };
  };

  config = lib.mkIf (cfg.hostname != null) {
    sops.secrets.nebula_ca_cert.sopsFile = k8sWorkerFile;
    sops.secrets.k8s_ca_cert.sopsFile = k8sWorkerFile;
    sops.secrets.k8s_bootstrap_token.sopsFile = k8sWorkerFile;
    sops.secrets.nebula_host_cert.sopsFile = cfg.nebulaFile;
    sops.secrets.nebula_host_key.sopsFile = cfg.nebulaFile;

    ducktape.nebulaMesh = {
      caCertPath = config.sops.secrets.nebula_ca_cert.path;
      hostCertPath = config.sops.secrets.nebula_host_cert.path;
      hostKeyPath = config.sops.secrets.nebula_host_key.path;
    };

    ducktape.k8sWorker = {
      caCertPath = config.sops.secrets.k8s_ca_cert.path;
      bootstrapTokenPath = config.sops.secrets.k8s_bootstrap_token.path;
    };
  };
}
