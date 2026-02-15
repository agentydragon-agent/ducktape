variable "authentik_url" {
  description = "Authentik server URL (internal)"
  type        = string
}

variable "authentik_token" {
  description = "Authentik API token"
  type        = string
  sensitive   = true
}

variable "loki_url" {
  description = "Loki external URL"
  type        = string
}
