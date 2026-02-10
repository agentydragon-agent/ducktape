variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region for Route 53 API calls"
}

variable "route53_zone_id" {
  type        = string
  description = "Route 53 hosted zone ID for allegedly.works"
}

variable "powerdns_url" {
  type        = string
  default     = "http://powerdns-api.dns-system:8081"
  description = "PowerDNS API URL (cluster-internal)"
}

variable "powerdns_api_key" {
  type        = string
  sensitive   = true
  description = "PowerDNS API key for record management"
}
