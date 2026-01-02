# VLAN 4 Network Configuration for Kubernetes Cluster
# Creates isolated network segment on 10.2.0.0/16

# VLAN 4 interface on physical NIC
resource "proxmox_virtual_environment_network_linux_vlan" "cluster_vlan" {
  node_name = var.proxmox_node_name
  name      = "enp10s0.4"
  comment   = "VLAN 4 - Kubernetes Cluster Network"
}

# Bridge for VLAN 4
resource "proxmox_virtual_environment_network_linux_bridge" "cluster_bridge" {
  depends_on = [proxmox_virtual_environment_network_linux_vlan.cluster_vlan]

  node_name = var.proxmox_node_name
  name      = "vmbr4"
  ports     = ["enp10s0.4"]
  autostart = true
  comment   = "VLAN 4 Bridge - Kubernetes Cluster"
}
