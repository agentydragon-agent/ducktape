# DNS MODULE VARIABLES

variable "cluster_domain" {
  description = "Cluster domain name"
  type        = string
}

variable "cluster_vip" {
  description = "Cluster VIP for API endpoint DNS record"
  type        = string
}

variable "ingress_pool" {
  description = "Ingress pool IP for wildcard DNS record"
  type        = string
  default     = "10.0.3.2"
}

