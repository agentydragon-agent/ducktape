# LAYER 2: Services Provider Versions

terraform {
  required_version = ">= 1.0"

  backend "local" {
    path = "terraform.tfstate"
  }

  required_providers {
    # Service deployment providers
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.1.0"
    }
    flux = {
      source  = "fluxcd/flux"
      version = "~> 1.7.0"
    }
  }
}