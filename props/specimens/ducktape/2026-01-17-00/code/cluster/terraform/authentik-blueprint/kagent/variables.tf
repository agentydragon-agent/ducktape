variable "authentik_url" {
  description = "Authentik server URL"
  type        = string
}

variable "authentik_token" {
  description = "Authentik API token"
  type        = string
  sensitive   = true
}

variable "kagent_url" {
  description = "Kagent external URL"
  type        = string
}
