variable "authentik_url" {
  description = "Authentik server URL (internal)"
  type        = string
}

variable "authentik_token" {
  description = "Authentik API token"
  type        = string
  sensitive   = true
}

variable "hubble_url" {
  description = "Hubble UI external URL"
  type        = string
}
