# LAYER 1: HYBRID INFRASTRUCTURE
# 3-node Talos cluster: 2x Hetzner VPS (controlplane) + 1x Proxmox home (controlplane)
# Machine secrets generated fresh per lifecycle (prevents stale KubeSpan discovery)

# ============================================================================
# REMOTE STATE: Import shared secrets from persistent auth layer
# ============================================================================

data "terraform_remote_state" "persistent_auth" {
  backend = "local"
  config = {
    path = "../persistent-auth/terraform.tfstate"
  }
}


# ============================================================================
# LOCALS: Shared configuration for all nodes
# ============================================================================

locals {
  # Machine secrets generated locally (fresh per lifecycle)
  machine_secrets      = talos_machine_secrets.cluster.machine_secrets
  client_configuration = talos_machine_secrets.cluster.client_configuration

  # Cluster configuration
  cluster_endpoint = "https://localhost:7445" # KubePrism - avoids circular dependency

  # Node topology - VPS nodes (controlplane + schedulable)
  vps_nodes = {
    vps0 = { name = "talos-vps-cp-0", server_type = "cpx31" }
    vps1 = { name = "talos-vps-cp-1", server_type = "cpx31" }
  }

  # Node topology - Proxmox nodes
  # Using VM IDs 10000+ to avoid conflicts with existing cluster (1500-2002)
  proxmox_nodes = {
    pve_cp0 = { name = "talos-pve-cp-0", type = "controlplane", vm_id = 10000, ip = "10.2.1.1" }
  }

  # GPU worker nodes (separate: different image, VFIO passthrough, NVIDIA config)
  proxmox_gpu_nodes = {
    pve_gpu_worker0 = { name = "talos-pve-gpu-worker-0", type = "worker", vm_id = 10100, ip = "10.2.2.1" }
  }

  # Proxmox network configuration
  proxmox_gateway = "10.2.0.1"

  # Bootstrap from first VPS (has public IP, most reliable for initial bootstrap)
  bootstrap_node = "vps0"

  # Total expected node count (for health checks)
  expected_node_count = length(local.vps_nodes) + length(local.proxmox_nodes) + length(local.proxmox_gpu_nodes)

  # All controlplane endpoints (for talosconfig) - VPS IPs + Proxmox controlplane IPs
  all_controlplane_ips = concat(
    [for k, v in hcloud_server.vps : v.ipv4_address],
    [for k, v in local.proxmox_nodes : v.ip if v.type == "controlplane"]
  )

  # Containerd registry mirrors — pull through Harbor proxy cache.
  # Harbor runs in-cluster, so mirrors are unavailable during early bootstrap.
  # Containerd falls back to upstream endpoints when mirror is unreachable.
  registry_mirrors = {
    "docker.io" = {
      endpoints = [
        "https://registry.allegedly.works/v2/docker-hub-proxy",
        "https://registry-1.docker.io",
      ]
    }
    "ghcr.io" = {
      endpoints = [
        "https://registry.allegedly.works/v2/ghcr-proxy",
        "https://ghcr.io",
      ]
    }
    "gcr.io" = {
      endpoints = [
        "https://registry.allegedly.works/v2/gcr-proxy",
        "https://gcr.io",
      ]
    }
    "quay.io" = {
      endpoints = [
        "https://registry.allegedly.works/v2/quay-proxy",
        "https://quay.io",
      ]
    }
    "registry.k8s.io" = {
      endpoints = [
        "https://registry.allegedly.works/v2/registry-k8s-io-proxy",
        "https://registry.k8s.io",
      ]
    }
  }
}

# ============================================================================
# PROVIDERS
# ============================================================================

# Hetzner Cloud
provider "hcloud" {
  token = var.hcloud_token
}

# Proxmox for home nodes
provider "proxmox" {
  endpoint  = "https://${var.proxmox_api_host}:8006/"
  username  = "terraform@pve"
  api_token = data.terraform_remote_state.persistent_auth.outputs.terraform_pve_token.token
  insecure  = true # Self-signed cert

  # SSH config for file uploads (cloud-init snippets)
  ssh {
    agent    = true
    username = "root"
    node {
      name    = var.proxmox_node_name
      address = var.proxmox_node_name # Direct Tailscale access
    }
  }
}

# Kubernetes provider - configured after cluster bootstrap
provider "kubernetes" {
  host                   = "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
  client_certificate     = base64decode(talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.client_certificate)
  client_key             = base64decode(talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.client_key)
  cluster_ca_certificate = base64decode(talos_cluster_kubeconfig.cluster.kubernetes_client_configuration.ca_certificate)
}

# ============================================================================
# HETZNER VPS NODES (see hetzner-nodes.tf for server resources)
# ============================================================================

# SSH key for emergency rescue mode access
resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "hcloud_ssh_key" "talos" {
  name       = "talos-cluster"
  public_key = tls_private_key.ssh.public_key_openssh
}

# Firewall for Talos/Kubernetes traffic
resource "hcloud_firewall" "talos" {
  name = "talos-cluster"

  # Kubernetes API
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "6443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Kubernetes API proxy (publicly-trusted TLS)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "16443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Talos API
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "50000"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Talos trustd (cluster join)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "50001"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # KubeSpan (WireGuard)
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "51820"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Cilium VXLAN overlay (between nodes)
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "8472"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Cilium health checks (cluster health probes between nodes)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "4240"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTPS ingress
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTP (for ACME)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # DNS (TCP)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "53"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # DNS (UDP)
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "53"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # etcd (between controllers)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "2379-2380"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # Kubelet API
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "10250"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # ICMP (ping)
  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

# ============================================================================
# TALOS BOOTSTRAP & KUBECONFIG
# ============================================================================

# Bootstrap etcd on the first VPS node. All other nodes are already configured
# and waiting in the etcd join retry loop — they join automatically after this.
resource "talos_machine_bootstrap" "cluster" {
  client_configuration = local.client_configuration
  endpoint             = hcloud_server.vps[local.bootstrap_node].ipv4_address
  node                 = hcloud_server.vps[local.bootstrap_node].ipv4_address

  depends_on = [
    talos_machine_configuration_apply.vps,
    talos_machine_configuration_apply.proxmox,
    talos_machine_configuration_apply.proxmox_gpu,
  ]
}

# Generate kubeconfig
resource "talos_cluster_kubeconfig" "cluster" {
  client_configuration = local.client_configuration
  endpoint             = hcloud_server.vps[local.bootstrap_node].ipv4_address
  node                 = hcloud_server.vps[local.bootstrap_node].ipv4_address

  depends_on = [talos_machine_bootstrap.cluster]
}

# Generate talosconfig
data "talos_client_configuration" "cluster" {
  cluster_name         = var.cluster_name
  client_configuration = local.client_configuration
  endpoints            = local.all_controlplane_ips
}

# ============================================================================
# LOCAL FILES
# ============================================================================

# Write kubeconfig to file (patched with real IP for external access)
resource "local_file" "kubeconfig" {
  content = replace(
    talos_cluster_kubeconfig.cluster.kubeconfig_raw,
    "https://localhost:7445",
    "https://${hcloud_server.vps[local.bootstrap_node].ipv4_address}:6443"
  )
  filename = "${path.module}/kubeconfig"
}

# Write talosconfig to file
resource "local_file" "talosconfig" {
  content  = data.talos_client_configuration.cluster.talos_config
  filename = "${path.module}/talosconfig.yml"
}
