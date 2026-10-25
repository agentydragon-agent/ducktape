terraform {
  required_version = ">= 1.0"
}

# This output-only root is a safe target for testing source repins and OpenTofu runs.
# It creates no external infrastructure; changing the value only changes state output.
output "source_update_canary" {
  description = "Output-only canary for testing source updates without creating infrastructure."
  value       = "canary-v1"
}
