# Proxmox VM Module Variables

variable "vm_name" {
  description = "Name of the VM"
  type        = string
}

variable "vm_id" {
  description = "VM ID in Proxmox (leave null for auto-assignment)"
  type        = number
  default     = null
}

variable "username" {
  description = "Username for VM user account"
  type        = string
  default     = "user"
}

variable "vcpus" {
  description = "Number of vCPUs"
  type        = number
  default     = 4
}

variable "memory_mb" {
  description = "Memory in MB"
  type        = number
  default     = 8192
}

variable "disk_size_gb" {
  description = "Disk size in GB"
  type        = number
  default     = 50
}

variable "auto_start" {
  description = "Start VM after creation"
  type        = bool
  default     = true
}

# Image import path on Proxmox (e.g., "local:import/wyrm2.qcow2")
variable "image_import_path" {
  description = "Proxmox storage path for the pre-built qcow2 image to import as the VM disk"
  type        = string
}

# Passed from parent (infrastructure context)
variable "proxmox_node_name" {
  description = "Proxmox node name"
  type        = string
}

variable "storage" {
  description = "Storage location for VM disk"
  type        = string
}

variable "network_bridge" {
  description = "Network bridge for VM"
  type        = string
}

variable "pool_id" {
  description = "Proxmox pool ID to place VM in (empty string = no pool)"
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key for VM access"
  type        = string
}

variable "machine_type" {
  description = "Machine type (null = provider default; 'q35' required for PCIe passthrough)"
  type        = string
  default     = null
}

variable "memory_floating_mb" {
  description = "Balloon minimum memory in MB (0 = disable balloon for VFIO; null = provider default)"
  type        = number
  default     = null
}

variable "gpu_pci_ids" {
  description = "Raw PCI device IDs for GPU passthrough (e.g. '0000:01:00.0')"
  type        = list(string)
  default     = []
}

variable "additional_disks" {
  description = "Additional data disks to attach at explicit SCSI slot numbers"
  type = list(object({
    interface    = string # SCSI interface, e.g. "scsi30"
    size_gb      = number
    datastore_id = optional(string) # Defaults to var.storage
  }))
  default = []
}

variable "virtiofs_mounts" {
  description = "Virtiofs shared filesystem mounts from Proxmox host"
  type = list(object({
    mapping = string           # Proxmox directory mapping ID
    cache   = optional(string) # Cache policy: "auto", "always", "metadata", "never"
  }))
  default = []
}

variable "vga_type" {
  description = "VGA display type (e.g. 'virtio', 'qxl', null for provider default)"
  type        = string
  default     = null
}

variable "vga_memory_mb" {
  description = "VGA memory in MiB (virtio-gpu needs >=256 for composited desktops)"
  type        = number
  default     = 256
}

# K8s cluster join credentials (optional)
variable "k8s_cluster_join" {
  description = "K8s cluster join credentials. When set, cloud-init writes credential files for kubelet and Nebula mesh."
  type = object({
    bootstrap_kubeconfig = string
    ca_cert              = string
    node_name            = string
    nebula_ca_cert       = string
    nebula_host_cert     = string
    nebula_host_key      = string
    nebula_config        = string
  })
  default   = null
  sensitive = true
}
