# Nebula Mesh — per-node machine config patches
#
# PKI (CA + node certs) is managed in persistent-auth.tf (same root).
# To add a new node, add it to local.nebula_nodes in persistent-auth.tf.

locals {
  nebula_ca_cert = data.local_file.nebula_ca_crt.content

  # Lighthouse topology from shared config (single source of truth)
  nebula_mesh_config    = jsondecode(file("${path.module}/../../../nebula-mesh.json"))
  nebula_lighthouse_ips = local.nebula_mesh_config.lighthouse_ips

  # Maps TF node keys → persistent-auth node names for cert lookup
  nebula_node_names = {
    vps0    = "talos-vps-cp-0"
    vps1    = "talos-vps-cp-1"
    pve_cp0 = "talos-pve-cp-0"
  }

  nebula_certs = {
    for key, name in local.nebula_node_names :
    key => {
      cert = data.local_file.nebula_node_crt[name].content
      key  = data.local_sensitive_file.nebula_node_key[name].content
    }
  }

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

  # Fields shared by all nebula nodes — merged with per-node overrides below
  nebula_common = {
    pki             = local.nebula_pki
    static_host_map = local.nebula_static_host_map
    listen          = { host = "0.0.0.0", port = 4242 }
    punchy          = { punch = true, respond = true }
    tun             = { dev = "nebula1" }
    logging         = { level = "info", format = "json" }
    timers = {
      connection_alive_interval = 5
      pending_deletion_interval = 10
    }
    firewall = local.nebula_firewall
  }

  # Per-node Nebula daemon configurations (common fields + per-node overrides)
  nebula_configs = {
    # VPS lighthouses: am_lighthouse + am_relay (relay required for NAT'd home nodes)
    vps0 = merge(local.nebula_common, {
      lighthouse = {
        am_lighthouse = true
        serve_dns     = true
        interval      = 10
        dns           = { host = "10.42.0.1", port = 53 }
      }
      relay = { am_relay = true }
    })
    vps1 = merge(local.nebula_common, {
      lighthouse = {
        am_lighthouse = true
        serve_dns     = true
        interval      = 10
        dns           = { host = "10.42.0.2", port = 53 }
      }
      relay = { am_relay = true }
    })
    # Proxmox home node: not a lighthouse, uses VPS relays for NAT traversal
    pve_cp0 = merge(local.nebula_common, {
      lighthouse = {
        am_lighthouse = false
        interval      = 10
        hosts         = local.nebula_lighthouse_ips
      }
      relay = { relays = local.nebula_lighthouse_ips, use_relays = true }
    })
  }

  # Per-node ExtensionServiceConfig documents (apiVersion: v1alpha1 /
  # kind: ExtensionServiceConfig): mount Nebula certs + config into the extension
  # service's filesystem. The extension runs: nebula -config /usr/local/etc/nebula/config.yml
  nebula_extension_config = {
    for key, _ in local.nebula_node_names :
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
  nebula_machine_patches = {
    for key in keys(local.nebula_node_names) :
    key => [local.nebula_extension_config[key]]
  }
}
