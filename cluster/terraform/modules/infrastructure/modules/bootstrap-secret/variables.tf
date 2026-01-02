variable "name" {
  description = "Secret name (e.g., vault-bootstrap)"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.name))
    error_message = "Secret name must be a valid Kubernetes resource name."
  }
}

variable "namespace" {
  description = "Kubernetes namespace"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.namespace))
    error_message = "Namespace must be a valid Kubernetes namespace name."
  }
}

variable "secret_key" {
  description = "Key name within the secret (e.g., root-token)"
  type        = string
  validation {
    condition     = length(var.secret_key) > 0
    error_message = "Secret key cannot be empty."
  }
}

variable "service_name" {
  description = "Service name for file paths (e.g., vault)"
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9]+$", var.service_name))
    error_message = "Service name must contain only lowercase letters and numbers."
  }
}

variable "cluster_root" {
  description = "Path to cluster root directory"
  type        = string
}