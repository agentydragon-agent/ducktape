variable "authentik_url" {
  description = "Authentik server URL"
  type        = string
  # No default - must be provided by caller
}

variable "authentik_token" {
  description = "Authentik API token"
  type        = string
  sensitive   = true
}

variable "harbor_url" {
  description = "Harbor server URL"
  type        = string
  default     = "https://registry.test-cluster.agentydragon.com"
}

variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}

# Note: harbor_admin_password is read directly from kubernetes_secret data source
# See harbor-config.tf for implementation