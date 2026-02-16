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
  description = "Harbor server URL (for OIDC redirect URI)"
  type        = string
  default     = "https://registry.allegedly.works"
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

variable "rotation_version" {
  description = "Bump to trigger secret rotation"
  type        = string
  default     = "1"
}
