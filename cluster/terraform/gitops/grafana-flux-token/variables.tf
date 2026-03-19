variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "vault_token" {
  description = "Vault authentication token"
  type        = string
  sensitive   = true
}

variable "grafana_url" {
  description = "Grafana base URL"
  type        = string
  default     = "https://grafana.allegedly.works"
}
