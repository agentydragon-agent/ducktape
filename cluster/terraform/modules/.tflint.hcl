plugin "terraform" {
  enabled = true
  version = "0.10.0"
  source  = "github.com/terraform-linters/tflint-ruleset-terraform"
}

# Module-specific configuration
# Modules inherit provider versions from root, so don't require them

rule "terraform_required_version" {
  enabled = false  # Modules inherit from root terraform configuration
}

rule "terraform_required_providers" {
  enabled = true   # Still check provider sources are specified
}

rule "terraform_unused_required_providers" {
  enabled = true   # Check for truly unused providers within modules
}

rule "terraform_standard_module_structure" {
  enabled = true   # Enforce proper module structure for reusable modules
}

rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_documented_variables" {
  enabled = true
}

rule "terraform_naming_convention" {
  enabled = true
  format  = "snake_case"
}