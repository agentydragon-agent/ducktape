# Nebula Mesh — PKI and per-node machine config patches
#
# Prerequisite: Generate certs with nebula-cert before running tofu apply:
#
#   nebula-cert ca -name "allegedly.works" -duration 87600h
#   mv ca.key cluster/terraform/bootstrap/persistent-auth/nebula-ca.key
#   mv ca.crt cluster/terraform/bootstrap/infrastructure/nebula/ca.crt
#
#   For each node (see Phase 1 in kubespand → Nebula migration plan):
#   nebula-cert sign -ca-crt nebula/ca.crt -ca-key ../persistent-auth/nebula-ca.key \
#     -name "talos-vps-cp-0" -ip "10.42.0.1/16" \
#     -groups "lighthouse,controlplane,vps" \
#     -out-crt nebula/talos-vps-cp-0.crt \
#     -out-key nebula/talos-vps-cp-0.key
#   (repeat for talos-vps-cp-1, talos-pve-cp-0, wyrm2, rugged, k8s-worker-test)
#
# CA key is stored in persistent-auth (never committed to git).
# Node certs and keys are gitignored (nebula/.gitignore).
# Only ca.crt is committed (public — safe to share).

locals {
  nebula_ca_cert = file("${path.module}/nebula/ca.crt")

  # VPS public IPs for the static host map — lighthouses must be reachable by IP
  nebula_static_host_map = {
    "10.42.0.1" = ["${hcloud_server.vps["vps0"].ipv4_address}:4242"]
    "10.42.0.2" = ["${hcloud_server.vps["vps1"].ipv4_address}:4242"]
  }

  # PKI paths — must match mountPath values in extensionServiceConfigs below
  nebula_pki = {
    ca   = "/usr/local/etc/nebula/ca.crt"
    cert = "/usr/local/etc/nebula/host.crt"
    key  = "/usr/local/etc/nebula/host.key"
  }

  # Allow all traffic — CiliumNetworkPolicy handles in-cluster isolation
  nebula_firewall = {
    outbound = [{ port = "any", proto = "any", host = "any" }]
    inbound  = [{ port = "any", proto = "any", host = "any" }]
  }

  # Per-node Nebula daemon configurations
  nebula_configs = {
    # VPS lighthouses: am_lighthouse + am_relay (relay required for NAT'd home nodes)
    vps0 = {
      pki             = local.nebula_pki
      static_host_map = local.nebula_static_host_map
      lighthouse      = { am_lighthouse = true, interval = 10 }
      relay           = { am_relay = true }
      listen          = { host = "0.0.0.0", port = 4242 }
      punchy          = { punch = true, respond = true }
      tun             = { dev = "nebula1" }
      firewall        = local.nebula_firewall
    }
    vps1 = {
      pki             = local.nebula_pki
      static_host_map = local.nebula_static_host_map
      lighthouse      = { am_lighthouse = true, interval = 10 }
      relay           = { am_relay = true }
      listen          = { host = "0.0.0.0", port = 4242 }
      punchy          = { punch = true, respond = true }
      tun             = { dev = "nebula1" }
      firewall        = local.nebula_firewall
    }
    # Proxmox home node: not a lighthouse, uses VPS relays for NAT traversal
    pve_cp0 = {
      pki             = local.nebula_pki
      static_host_map = local.nebula_static_host_map
      lighthouse = {
        am_lighthouse = false
        interval      = 10
        hosts         = ["10.42.0.1", "10.42.0.2"]
      }
      relay    = { relays = ["10.42.0.1", "10.42.0.2"], use_relays = true }
      listen   = { host = "0.0.0.0", port = 4242 }
      punchy   = { punch = true, respond = true }
      tun      = { dev = "nebula1" }
      firewall = local.nebula_firewall
    }
  }

  # Maps TF node keys → node names used for cert filenames
  nebula_cert_paths = {
    vps0    = "talos-vps-cp-0"
    vps1    = "talos-vps-cp-1"
    pve_cp0 = "talos-pve-cp-0"
  }

  nebula_certs = {
    for key, node_name in local.nebula_cert_paths :
    key => {
      cert = file("${path.module}/nebula/${node_name}.crt")
      key  = file("${path.module}/nebula/${node_name}.key")
    }
  }

  # Nebula machine config patches per node — two separate documents:
  #
  # 1. Standard machine config patch: set kubelet.nodeIP.validSubnets so kubelet
  #    registers with its Nebula IP (10.42.0.x). Talos extension services start
  #    before kubelet, so nebula1 exists when kubelet selects its IP.
  #
  # 2. ExtensionServiceConfig document (apiVersion: v1alpha1 / kind: ExtensionServiceConfig):
  #    mounts Nebula certs + config into the extension service's filesystem.
  #    This is a separate Talos document type, NOT a field under machine:.
  #    The extension runs: nebula -config /usr/local/etc/nebula/config.yml

  # tflint-ignore: terraform_unused_declarations — needed in Pass B after KubeSpan disabled
  # Uncomment in Pass B after KubeSpan is disabled:
  # nebula_kubelet_patch = yamlencode({
  #   machine = {
  #     kubelet = {
  #       nodeIP = {
  #         validSubnets = ["10.42.0.0/16"]
  #       }
  #     }
  #   }
  # })

  nebula_extension_config = {
    for key, node_name in local.nebula_cert_paths :
    key => yamlencode({
      apiVersion = "v1alpha1"
      kind       = "ExtensionServiceConfig"
      name       = "nebula"
      configFiles = [
        {
          mountPath = "/usr/local/etc/nebula/ca.crt"
          content   = local.nebula_ca_cert
        },
        {
          mountPath = "/usr/local/etc/nebula/host.crt"
          content   = local.nebula_certs[key].cert
        },
        {
          mountPath = "/usr/local/etc/nebula/host.key"
          content   = local.nebula_certs[key].key
        },
        {
          mountPath = "/usr/local/etc/nebula/config.yml"
          content   = yamlencode(local.nebula_configs[key])
        },
      ]
    })
  }

  # Combined list of patches per node (used in config_patches concat).
  # NOTE: nebula_kubelet_patch (nodeIP.validSubnets → 10.42.0.0/16) is NOT
  # included here — it must only be applied in Pass B after KubeSpan is disabled.
  # Applying it while KubeSpan is active breaks etcd peering (kubelet registers
  # with Nebula IP but KubeSpan can't route to it).
  nebula_machine_patches = {
    for key in keys(local.nebula_cert_paths) :
    key => [local.nebula_extension_config[key]]
  }
}
