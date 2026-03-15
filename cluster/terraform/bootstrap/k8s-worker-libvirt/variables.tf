# K8s Worker (Libvirt) Variables

variable "libvirt_uri" {
  description = "Libvirt connection URI"
  type        = string
  default     = "qemu:///system"
}

variable "libvirt_storage_pool" {
  description = "Libvirt storage pool for VM volumes"
  type        = string
  default     = "default"
}

variable "libvirt_network_name" {
  description = "Libvirt network for VM"
  type        = string
  default     = "default"
}

variable "uefi_firmware_path" {
  description = "Path to UEFI firmware (OVMF)"
  type        = string
  default     = "/usr/share/OVMF/OVMF_CODE_4M.fd"
}

variable "ssh_public_key" {
  description = "SSH public key (auto-detected from ~/.ssh if not specified)"
  type        = string
  default     = ""
}
