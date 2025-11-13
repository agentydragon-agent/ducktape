# Variables for Application Configuration

# Vault Configuration
variable "vault_address" {
  description = "Vault server address"
  type        = string
  default     = "https://vault.k3s.agentydragon.com"
}

# Authentik Configuration
variable "authentik_url" {
  description = "Authentik API URL"
  type        = string
  default     = "https://auth.k3s.agentydragon.com"
}

# Authentik API token is now auto-generated via Kubernetes

variable "authentik_external_url" {
  description = "External URL for Authentik (user-facing)"
  type        = string
  default     = "https://auth.k3s.agentydragon.com"
}

# Harbor Configuration  
variable "harbor_url" {
  description = "Harbor API URL"
  type        = string
  default     = "https://registry.k3s.agentydragon.com"
}

variable "harbor_username" {
  description = "Harbor admin username"
  type        = string
  default     = "admin"
}

# Harbor password is now retrieved from Vault

variable "harbor_external_url" {
  description = "External URL for Harbor (user-facing)"
  type        = string
  default     = "https://registry.k3s.agentydragon.com"
}

variable "harbor_admin_group" {
  description = "Authentik group name for Harbor administrators"
  type        = string
  default     = "harbor-terraform-admins"
}

# Kubernetes Configuration
variable "kubeconfig_path" {
  description = "Path to kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}