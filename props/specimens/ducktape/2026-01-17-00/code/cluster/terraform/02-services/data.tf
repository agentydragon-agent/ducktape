# LAYER 2 DATA SOURCES
# References to infrastructure and persistent auth layer outputs

data "terraform_remote_state" "infrastructure" {
  backend = "local"
  config = {
    path = "../01-infrastructure/terraform.tfstate"
  }
}

data "terraform_remote_state" "persistent_auth" {
  backend = "local"
  config = {
    path = "../00-persistent-auth/terraform.tfstate"
  }
}
