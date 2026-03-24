variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "rotation_version" {
  description = "Bump to trigger secret rotation"
  type        = string
  default     = "1"
}
