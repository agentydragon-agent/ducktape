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
