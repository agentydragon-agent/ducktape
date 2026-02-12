# LAYER 2 (FLUX) DATA SOURCES
# References to infrastructure and persistent auth layer outputs

data "terraform_remote_state" "infrastructure" {
  backend = "local"
  config = {
    path = "../infrastructure/terraform.tfstate"
  }
}

data "terraform_remote_state" "persistent_auth" {
  backend = "local"
  config = {
    path = "../persistent-auth/terraform.tfstate"
  }
}
