variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}

variable "headscale_url" {
  description = "Headscale API endpoint URL"
  type        = string
}

variable "headscale_api_key" {
  description = "Headscale API key"
  type        = string
  sensitive   = true
}
