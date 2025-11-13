# Variables for Harbor + Authentik OIDC Configuration

variable "harbor_external_url" {
  description = "External URL for Harbor registry"
  type        = string
  default     = "https://registry.k3s.agentydragon.com"
}

variable "authentik_external_url" {
  description = "External URL for Authentik"
  type        = string
  default     = "https://auth.k3s.agentydragon.com"
}

variable "harbor_admin_group" {
  description = "Authentik group name for Harbor administrators"
  type        = string
  default     = "harbor-admins"
}

variable "harbor_client_secret" {
  description = "Harbor OIDC client secret (generated externally)"
  type        = string
  sensitive   = true
}