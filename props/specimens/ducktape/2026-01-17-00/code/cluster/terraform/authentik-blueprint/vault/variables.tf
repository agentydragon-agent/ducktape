variable "authentik_url" {
  description = "Authentik server URL"
  type        = string
}

variable "authentik_token" {
  description = "Authentik API token"
  type        = string
  sensitive   = true
}

variable "vault_url" {
  description = "Vault server URL"
  type        = string
  default     = "https://vault.test-cluster.agentydragon.com"
}

variable "vault_address" {
  description = "Vault API address for provider"
  type        = string
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}
