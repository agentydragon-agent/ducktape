variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}

variable "vault_external_url" {
  description = "External Vault URL for OIDC redirects"
  type        = string
  default     = "https://vault.test-cluster.agentydragon.com"
}

variable "authentik_oidc_discovery_url" {
  description = "Authentik OIDC discovery URL"
  type        = string
  default     = "http://authentik-server.authentik/application/o/vault/"
}

variable "vault_client_secret" {
  description = "OIDC client secret for Vault"
  type        = string
  sensitive   = true
  default     = ""
}