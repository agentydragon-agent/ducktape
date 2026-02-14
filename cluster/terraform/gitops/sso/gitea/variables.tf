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

variable "gitea_url" {
  description = "Gitea server URL"
  type        = string
  default     = "https://git.allegedly.works"
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
