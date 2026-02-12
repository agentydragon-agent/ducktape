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

variable "user_password" {
  description = "Password for the agentydragon user"
  type        = string
  sensitive   = true
}
