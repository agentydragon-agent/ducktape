output "secret_name" {
  description = "Name of the generated secret"
  value       = var.name
}

output "sealed_secret_path" {
  description = "Path to the sealed secret file"
  value       = local.sealed_secret_path
}

output "generated" {
  description = "Whether the secret was generated (vs already existed)"
  value       = !fileexists(local.sealed_secret_path)
}