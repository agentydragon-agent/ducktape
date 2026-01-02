# DNS MODULE OUTPUTS

output "powerdns_api_key" {
  description = "Generated PowerDNS API key"
  value       = random_password.powerdns_api_key.result
  sensitive   = true
}

output "cluster_zone" {
  description = "Created DNS zone for cluster"
  value       = powerdns_zone.cluster_zone.name
}

output "dns_records" {
  description = "Created DNS records"
  value = {
    api_endpoint = powerdns_record.cluster_api.name
    wildcard     = powerdns_record.ingress.name
  }
}