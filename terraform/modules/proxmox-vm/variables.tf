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

variable "gpu_mappings" {
  description = "PCI hardware mapping names for GPU passthrough"
  type        = list(string)
  default     = []
}

variable "additional_disks" {
  description = "Additional data disks to attach at explicit SCSI slot numbers"
  type = list(object({
    interface    = string           # SCSI interface, e.g. "scsi30"
    size_gb      = number
    datastore_id = optional(string) # Defaults to var.storage
  }))
  default = []
}

# K8s cluster join credentials (optional)
variable "k8s_cluster_join" {
  description = "K8s cluster join credentials. When set, cloud-init writes credential files for kubelet and kubespand."
  type = object({
    bootstrap_kubeconfig = string
    ca_cert              = string
    cluster_id           = string
    cluster_secret       = string
    node_name            = string
  })
  default   = null
  sensitive = true
}
