variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "rotation_version" {
  description = "Bump to trigger secret rotation for all OAuth2 client secrets"
  type        = string
  default     = "1"
}
