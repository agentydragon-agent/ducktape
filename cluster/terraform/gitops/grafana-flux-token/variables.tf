variable "vault_address" {
  description = "Vault server address"
  type        = string
}

variable "grafana_url" {
  description = "Grafana base URL"
  type        = string
  default     = "https://grafana.allegedly.works"
}
