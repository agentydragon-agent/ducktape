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

variable "grafana_url" {
  description = "Grafana server URL"
  type        = string
  default     = "https://grafana.test-cluster.agentydragon.com"
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
