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
  secretsDir = ../../../../secrets;
in
{
  options.ducktape.k8sWorkerSops = {
    hostname = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Host name used to locate sops secret files (secrets/{hostname}-nebula.yaml).";
    };
  };

  config = lib.mkIf (cfg.hostname != null) {
    sops.secrets.nebula_ca_cert.sopsFile = secretsDir + "/k8s-worker.yaml";
    sops.secrets.k8s_ca_cert.sopsFile = secretsDir + "/k8s-worker.yaml";
    sops.secrets.k8s_bootstrap_token.sopsFile = secretsDir + "/k8s-worker.yaml";
    sops.secrets.nebula_host_cert.sopsFile = secretsDir + "/${cfg.hostname}-nebula.yaml";
    sops.secrets.nebula_host_key.sopsFile = secretsDir + "/${cfg.hostname}-nebula.yaml";

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
