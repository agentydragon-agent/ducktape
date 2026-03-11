variable "flake_target" {
  description = "Nix flake package name (e.g., 'lxc-k8s-test' builds nix#lxc-k8s-test-lxc)"
  type        = string
}

variable "proxmox_host" {
  description = "Proxmox host address for SCP upload"
  type        = string
}

variable "repo_root" {
  description = "Path to the repository root (for nix build)"
  type        = string
}

variable "nix_dir_hash" {
  description = "Hash of nix/ directory contents (triggers rebuild on change)"
  type        = string
}
