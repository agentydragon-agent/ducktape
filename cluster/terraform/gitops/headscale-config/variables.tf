variable "headscale_url" {
  description = "Headscale API endpoint URL"
  type        = string
}

variable "headscale_api_key" {
  description = "Headscale API key"
  type        = string
  sensitive   = true
}
